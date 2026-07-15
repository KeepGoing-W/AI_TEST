import re
from dataclasses import dataclass
from itertools import product
from typing import Any
from uuid import UUID

from app.modules.source_scans.models import RelationType, SymbolType

HTTP_METHODS = {
    "DeleteMapping": "DELETE",
    "GetMapping": "GET",
    "PatchMapping": "PATCH",
    "PostMapping": "POST",
    "PutMapping": "PUT",
}
PARAMETER_SOURCES = {
    "PathVariable": "path",
    "RequestBody": "body",
    "RequestHeader": "header",
    "RequestParam": "query",
}
DTO_SUFFIXES = ("Command", "DTO", "Request", "Response", "VO")
VALIDATION_ANNOTATIONS = {
    "DecimalMax",
    "DecimalMin",
    "Email",
    "Max",
    "Min",
    "Negative",
    "NegativeOrZero",
    "NotBlank",
    "NotEmpty",
    "NotNull",
    "Pattern",
    "Positive",
    "PositiveOrZero",
    "Size",
}


class JavaParseError(Exception):
    """表示 Java AST 解析器不可用或无法完成解析。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class ParsedCodeSymbol:
    """尚未持久化的代码符号。"""

    source_file_id: UUID
    symbol_type: SymbolType
    name: str
    qualified_name: str
    signature: str | None
    start_line: int
    end_line: int
    annotations: list[object]
    metadata: dict[str, object]
    parent_qualified_name: str | None = None


@dataclass(frozen=True)
class ParsedApiDefinition:
    """尚未持久化的源码接口定义。"""

    method: str
    normalized_path: str
    controller_qualified_name: str
    method_qualified_name: str
    request_definition: dict[str, object]
    source_definition: dict[str, object]


@dataclass(frozen=True)
class ParsedSymbolRelation:
    """尚未解析目标符号标识的关系。"""

    source_qualified_name: str
    target_name: str
    relation_type: RelationType
    metadata: dict[str, object]


@dataclass(frozen=True)
class JavaParseResult:
    """一批 Java 文件的 AST 解析结果。"""

    code_symbols: list[ParsedCodeSymbol]
    api_definitions: list[ParsedApiDefinition]
    symbol_relations: list[ParsedSymbolRelation]


def parse_java_sources(source_files: list[tuple[UUID, str]]) -> JavaParseResult:
    """使用 Tree-sitter 提取 Controller、方法和 Spring 路由。"""

    if not source_files:
        return JavaParseResult(code_symbols=[], api_definitions=[], symbol_relations=[])
    try:
        import tree_sitter_java
        from tree_sitter import Language, Parser
    except ImportError as exc:
        raise JavaParseError("JAVA_PARSER_UNAVAILABLE", "Java 源码解析器不可用") from exc

    try:
        parser = Parser(Language(tree_sitter_java.language()))
    except (TypeError, ValueError) as exc:
        raise JavaParseError("JAVA_PARSER_UNAVAILABLE", "Java 源码解析器版本不兼容") from exc
    code_symbols: list[ParsedCodeSymbol] = []
    api_definitions: list[ParsedApiDefinition] = []
    symbol_relations: list[ParsedSymbolRelation] = []
    for source_file_id, content in source_files:
        source_bytes = content.encode("utf-8")
        tree = parser.parse(source_bytes)
        if tree is None:
            raise JavaParseError("JAVA_PARSER_FAILED", "Java 源码解析失败")
        package_name = _package_name(tree.root_node, source_bytes)
        for node in tree.root_node.named_children:
            if node.type in {"class_declaration", "interface_declaration", "enum_declaration"}:
                result = _parse_type_declaration(node, source_file_id, source_bytes, package_name)
                code_symbols.extend(result.code_symbols)
                api_definitions.extend(result.api_definitions)
                symbol_relations.extend(result.symbol_relations)
    return JavaParseResult(
        code_symbols=code_symbols,
        api_definitions=api_definitions,
        symbol_relations=symbol_relations,
    )


def _parse_type_declaration(node: Any, source_file_id: UUID, source: bytes, package_name: str) -> JavaParseResult:
    class_name = _field_text(node, "name", source)
    if class_name is None:
        return JavaParseResult(code_symbols=[], api_definitions=[], symbol_relations=[])
    qualified_name = ".".join(part for part in [package_name, class_name] if part)
    annotations = _annotations(node, source)
    annotation_names = {_annotation_name(annotation) for annotation in annotations}
    is_controller = "RestController" in annotation_names
    class_symbol = ParsedCodeSymbol(
        source_file_id=source_file_id,
        symbol_type=_type_symbol_type(node.type, class_name, annotations, source),
        name=class_name,
        qualified_name=qualified_name,
        signature=None,
        start_line=node.start_point.row + 1,
        end_line=node.end_point.row + 1,
        annotations=annotations,
        metadata={"isController": is_controller, "role": _class_role(class_name, annotations, source)},
    )
    code_symbols = [class_symbol]
    api_definitions: list[ParsedApiDefinition] = []
    symbol_relations: list[ParsedSymbolRelation] = []
    body = _child(node, "class_body") or _child(node, "enum_body")
    if body is None:
        return JavaParseResult(
            code_symbols=code_symbols,
            api_definitions=api_definitions,
            symbol_relations=symbol_relations,
        )
    class_paths = _class_paths(annotations)
    field_types: dict[str, str] = {}
    for member in body.named_children:
        if member.type == "field_declaration":
            field_symbols, declared_fields = _parse_field_declaration(
                member, source_file_id, source, qualified_name, class_symbol.symbol_type
            )
            code_symbols.extend(field_symbols)
            field_types.update(declared_fields)
            symbol_relations.extend(
                _field_relations(qualified_name, declared_fields, class_symbol.symbol_type)
            )
            continue
        if member.type == "enum_constant":
            enum_symbol = _parse_enum_constant(member, source_file_id, source, qualified_name)
            if enum_symbol is not None:
                code_symbols.append(enum_symbol)
    for member in body.named_children:
        if member.type != "method_declaration":
            continue
        method_result = _parse_method_declaration(member, source_file_id, source, qualified_name, annotations)
        code_symbols.append(method_result[0])
        symbol_relations.extend(_method_relations(method_result[0], method_result[1], field_types, member, source))
        if is_controller:
            api_definitions.extend(_routes_for_method(method_result[0], method_result[1], class_paths, annotations))
    return JavaParseResult(
        code_symbols=code_symbols,
        api_definitions=api_definitions,
        symbol_relations=symbol_relations,
    )


def _parse_method_declaration(
    node: Any,
    source_file_id: UUID,
    source: bytes,
    class_qualified_name: str,
    class_annotations: list[str],
) -> tuple[ParsedCodeSymbol, list[dict[str, object]]]:
    method_name = _field_text(node, "name", source) or "unknown"
    parameters = _method_parameters(node, source)
    parameter_types = ",".join(str(parameter["type"]) for parameter in parameters)
    qualified_name = f"{class_qualified_name}.{method_name}({parameter_types})"
    annotations = _annotations(node, source)
    signature = _node_text(node, source).split("{", 1)[0].strip()
    return (
        ParsedCodeSymbol(
            source_file_id=source_file_id,
            symbol_type=SymbolType.METHOD,
            name=method_name,
            qualified_name=qualified_name,
            signature=signature,
            start_line=node.start_point.row + 1,
            end_line=node.end_point.row + 1,
            annotations=annotations,
            metadata={
                "isControllerMethod": "RestController"
                in {_annotation_name(annotation) for annotation in class_annotations}
            },
            parent_qualified_name=class_qualified_name,
        ),
        parameters,
    )


def _parse_field_declaration(
    node: Any,
    source_file_id: UUID,
    source: bytes,
    class_qualified_name: str,
    class_symbol_type: SymbolType,
) -> tuple[list[ParsedCodeSymbol], dict[str, str]]:
    field_type = _field_text(node, "type", source) or "unknown"
    annotations = _annotations(node, source)
    constraints = _validation_constraints(annotations)
    symbols: list[ParsedCodeSymbol] = []
    declared_fields: dict[str, str] = {}
    for declarator in node.named_children:
        if declarator.type != "variable_declarator":
            continue
        field_name = _field_text(declarator, "name", source)
        if field_name is None:
            continue
        metadata: dict[str, object] = {"declaredType": field_type, "constraints": constraints}
        error_code = _error_code_value(node, source, class_symbol_type)
        if error_code is not None:
            metadata["errorCode"] = error_code
        symbols.append(
            ParsedCodeSymbol(
                source_file_id=source_file_id,
                symbol_type=SymbolType.FIELD,
                name=field_name,
                qualified_name=f"{class_qualified_name}.{field_name}",
                signature=field_type,
                start_line=node.start_point.row + 1,
                end_line=node.end_point.row + 1,
                annotations=annotations,
                metadata=metadata,
                parent_qualified_name=class_qualified_name,
            )
        )
        declared_fields[field_name] = field_type
    return symbols, declared_fields


def _parse_enum_constant(
    node: Any, source_file_id: UUID, source: bytes, enum_qualified_name: str
) -> ParsedCodeSymbol | None:
    name = _field_text(node, "name", source) or _node_text(node, source).split("(", 1)[0].strip()
    if not name:
        return None
    metadata: dict[str, object] = {"enumValue": name}
    error_code = _enum_error_code(node, source)
    if error_code is not None:
        metadata["errorCode"] = error_code
    return ParsedCodeSymbol(
        source_file_id=source_file_id,
        symbol_type=SymbolType.FIELD,
        name=name,
        qualified_name=f"{enum_qualified_name}.{name}",
        signature=None,
        start_line=node.start_point.row + 1,
        end_line=node.end_point.row + 1,
        annotations=[],
        metadata=metadata,
        parent_qualified_name=enum_qualified_name,
    )


def _field_relations(
    class_qualified_name: str,
    declared_fields: dict[str, str],
    class_symbol_type: SymbolType,
) -> list[ParsedSymbolRelation]:
    if class_symbol_type not in {SymbolType.CLASS, SymbolType.REPOSITORY, SymbolType.MAPPER}:
        return []
    relations: list[ParsedSymbolRelation] = []
    for field_name, field_type in declared_fields.items():
        target_name = _referenced_type(field_type)
        if target_name is None:
            continue
        relations.append(
            ParsedSymbolRelation(
                source_qualified_name=class_qualified_name,
                target_name=target_name,
                relation_type=RelationType.REFERENCES,
                metadata={"field": field_name},
            )
        )
    return relations


def _method_relations(
    method_symbol: ParsedCodeSymbol,
    parameters: list[dict[str, object]],
    field_types: dict[str, str],
    node: Any,
    source: bytes,
) -> list[ParsedSymbolRelation]:
    relations: list[ParsedSymbolRelation] = []
    for parameter in parameters:
        if parameter["source"] != "body":
            continue
        target_name = _referenced_type(str(parameter["type"]))
        if target_name is not None:
            relations.append(
                ParsedSymbolRelation(
                    source_qualified_name=method_symbol.qualified_name,
                    target_name=target_name,
                    relation_type=RelationType.USES_DTO,
                    metadata={"parameter": parameter["name"]},
                )
            )
    method_text = _node_text(node, source)
    for field_name, field_type in field_types.items():
        if re.search(rf"\b{re.escape(field_name)}\s*\.", method_text) is None:
            continue
        target_name = _referenced_type(field_type)
        if target_name is not None:
            relations.append(
                ParsedSymbolRelation(
                    source_qualified_name=method_symbol.qualified_name,
                    target_name=target_name,
                    relation_type=RelationType.CALLS,
                    metadata={"field": field_name},
                )
            )
    for exception_name in re.findall(r"\bthrow\s+new\s+([A-Za-z_]\w*)", method_text):
        relations.append(
            ParsedSymbolRelation(
                source_qualified_name=method_symbol.qualified_name,
                target_name=exception_name,
                relation_type=RelationType.THROWS,
                metadata={},
            )
        )
    return relations


def _routes_for_method(
    method_symbol: ParsedCodeSymbol,
    parameters: list[dict[str, object]],
    class_paths: list[str],
    class_annotations: list[str],
) -> list[ParsedApiDefinition]:
    routes = _method_routes(method_symbol.annotations)
    definitions: list[ParsedApiDefinition] = []
    for http_method, method_paths in routes:
        for class_path, method_path in product(class_paths, method_paths):
            normalized_path = _normalize_path(class_path, method_path)
            definitions.append(
                ParsedApiDefinition(
                    method=http_method,
                    normalized_path=normalized_path,
                    controller_qualified_name=method_symbol.parent_qualified_name or "",
                    method_qualified_name=method_symbol.qualified_name,
                    request_definition={"parameters": parameters},
                    source_definition={
                        "controllerAnnotations": class_annotations,
                        "methodAnnotations": method_symbol.annotations,
                        "methodLine": method_symbol.start_line,
                    },
                )
            )
    return definitions


def _package_name(root: Any, source: bytes) -> str:
    package = _child(root, "package_declaration")
    if package is None:
        return ""
    return _node_text(package, source).removeprefix("package").removesuffix(";").strip()


def _class_paths(annotations: list[str]) -> list[str]:
    paths: list[str] = []
    for annotation in annotations:
        if _annotation_name(annotation) == "RequestMapping":
            paths.extend(_annotation_paths(annotation))
    return paths or [""]


def _method_routes(annotations: list[str]) -> list[tuple[str, list[str]]]:
    routes: list[tuple[str, list[str]]] = []
    for annotation in annotations:
        name = _annotation_name(annotation)
        if name in HTTP_METHODS:
            routes.append((HTTP_METHODS[name], _annotation_paths(annotation)))
        elif name == "RequestMapping":
            methods = re.findall(r"RequestMethod\.(GET|POST|PUT|PATCH|DELETE)", annotation)
            if methods:
                routes.extend((method, _annotation_paths(annotation)) for method in methods)
    return routes


def _method_parameters(node: Any, source: bytes) -> list[dict[str, object]]:
    parameters_node = _child(node, "formal_parameters")
    if parameters_node is None:
        return []
    parameters: list[dict[str, object]] = []
    for parameter in parameters_node.named_children:
        if parameter.type not in {"formal_parameter", "spread_parameter"}:
            continue
        annotations = _annotations(parameter, source)
        annotation_names = [_annotation_name(annotation) for annotation in annotations]
        source_type = next(
            (PARAMETER_SOURCES[name] for name in annotation_names if name in PARAMETER_SOURCES), "unknown"
        )
        parameters.append(
            {
                "name": _field_text(parameter, "name", source) or "unknown",
                "type": _field_text(parameter, "type", source) or "unknown",
                "source": source_type,
                "bindingName": _parameter_binding_name(annotations),
                "annotations": annotations,
            }
        )
    return parameters


def _parameter_binding_name(annotations: list[str]) -> str | None:
    for annotation in annotations:
        if _annotation_name(annotation) in PARAMETER_SOURCES:
            paths = _annotation_paths(annotation)
            return paths[0] if paths else None
    return None


def _annotations(node: Any, source: bytes) -> list[str]:
    modifiers = _child(node, "modifiers")
    if modifiers is None:
        return []
    return [_node_text(child, source) for child in modifiers.named_children if "annotation" in child.type]


def _annotation_name(annotation: str) -> str:
    match = re.match(r"@(?:[\w.]+\.)?([A-Za-z_][\w]*)", annotation)
    return match.group(1) if match else ""


def _annotation_paths(annotation: str) -> list[str]:
    values = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', annotation)
    return [bytes(value, "utf-8").decode("unicode_escape") for value in values] or [""]


def _normalize_path(class_path: str, method_path: str) -> str:
    segments = [segment.strip("/") for segment in [class_path, method_path] if segment.strip("/")]
    return "/" + "/".join(segments) if segments else "/"


def _type_symbol_type(node_type: str, name: str, annotations: list[str], source: bytes) -> SymbolType:
    if node_type == "enum_declaration":
        return SymbolType.ENUM
    if node_type == "interface_declaration":
        return SymbolType.INTERFACE
    role = _class_role(name, annotations, source)
    if role == "dto":
        return SymbolType.DTO
    if role == "exception":
        return SymbolType.EXCEPTION
    if role == "repository":
        return SymbolType.REPOSITORY
    if role == "mapper":
        return SymbolType.MAPPER
    return SymbolType.CLASS


def _class_role(name: str, annotations: list[str], _: bytes) -> str:
    annotation_names = {_annotation_name(annotation) for annotation in annotations}
    if name.endswith(DTO_SUFFIXES):
        return "dto"
    if name.endswith("Exception") or "ResponseStatus" in annotation_names:
        return "exception"
    if "Repository" in annotation_names or name.endswith(("Repository", "Dao")):
        return "repository"
    if "Mapper" in annotation_names or name.endswith("Mapper"):
        return "mapper"
    if "Service" in annotation_names or name.endswith("Service"):
        return "service"
    return "class"


def _validation_constraints(annotations: list[str]) -> list[dict[str, str]]:
    constraints: list[dict[str, str]] = []
    for annotation in annotations:
        name = _annotation_name(annotation)
        if name not in VALIDATION_ANNOTATIONS:
            continue
        arguments = annotation.partition("(")[2].rpartition(")")[0].strip()
        constraints.append({"name": name, "arguments": arguments})
    return constraints


def _error_code_value(node: Any, source: bytes, class_symbol_type: SymbolType) -> str | None:
    if class_symbol_type != SymbolType.EXCEPTION:
        return None
    return _literal_error_code(_node_text(node, source))


def _enum_error_code(node: Any, source: bytes) -> str | None:
    return _literal_error_code(_node_text(node, source))


def _literal_error_code(value: str) -> str | None:
    string_match = re.search(r'"([^"\\]*(?:\\.[^"\\]*)*)"', value)
    if string_match is not None:
        return string_match.group(1)
    number_match = re.search(r"\(\s*(-?\d+)", value)
    return number_match.group(1) if number_match is not None else None


def _referenced_type(type_name: str) -> str | None:
    names = re.findall(r"[A-Za-z_]\w*", type_name)
    if not names:
        return None
    return names[-1]


def _child(node: Any, node_type: str) -> Any | None:
    return next((child for child in node.named_children if child.type == node_type), None)


def _field_text(node: Any, field_name: str, source: bytes) -> str | None:
    field = node.child_by_field_name(field_name)
    return _node_text(field, source) if field is not None else None


def _node_text(node: Any, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8")
