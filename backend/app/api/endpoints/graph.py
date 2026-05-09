"""Knowledge graph API built from the current uploaded documents."""

import csv
from io import StringIO
import logging
from typing import Optional
from xml.etree import ElementTree

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from app.api.endpoints.auth import UserRecord, current_user_or_dev
from app.api.endpoints.documents_with_markdown import get_cached_parse, parse_document_file
from app.core.rate_limit import graph_read_limit
from app.services.document_service import document_service
from app.services.entity_extractor import entity_extractor
from app.services.graph_builder_enhanced import KnowledgeGraph, knowledge_graph


router = APIRouter()
log = logging.getLogger(__name__)


@router.get("/")
@graph_read_limit
async def get_graph(
    user: UserRecord = Depends(current_user_or_dev),
    request: Request = None,
) -> dict:
    """Return a graph built from all currently uploaded documents."""
    graph = rebuild_graph_from_documents(user.id)
    return graph.export_for_visualization()


@router.get("/stats")
@graph_read_limit
async def get_graph_stats(
    user: UserRecord = Depends(current_user_or_dev),
    request: Request = None,
) -> dict:
    """Return graph counters under the same read limit as the graph canvas."""
    graph = rebuild_graph_from_documents(user.id)
    return graph.get_stats()


@router.get("/nodes/{node_id}")
@graph_read_limit
async def get_node(
    node_id: str,
    user: UserRecord = Depends(current_user_or_dev),
    request: Request = None,
) -> dict:
    """Return one node plus its directly connected neighborhood."""
    graph = rebuild_graph_from_documents(user.id)
    node = graph.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    neighbors = graph.get_neighbors(node_id)
    return {"node": node, "neighbors": neighbors, "neighbor_count": len(neighbors)}


@router.get("/search")
@graph_read_limit
async def search_nodes(
    q: str = Query("", description="Label text to search for"),
    node_type: Optional[str] = Query(None, description="Optional node type filter"),
    limit: int = Query(10, ge=1, le=50),
    user: UserRecord = Depends(current_user_or_dev),
    request: Request = None,
) -> dict:
    """Search graph nodes by label."""
    graph = rebuild_graph_from_documents(user.id)
    return {"results": graph.search_nodes(q, node_type=node_type, limit=limit)}


@router.get("/debug")
@graph_read_limit
async def graph_debug(
    user: UserRecord = Depends(current_user_or_dev),
    request: Request = None,
) -> dict:
    """Return full node and edge metadata for development checks."""
    graph = rebuild_graph_from_documents(user.id)
    return {**graph.export_detailed(), "stats": graph.get_stats()}


@router.get("/export")
@graph_read_limit
async def export_graph(
    format: str = Query("json", pattern="^(json|gexf|csv)$"),
    user: UserRecord = Depends(current_user_or_dev),
    request: Request = None,
) -> Response:
    """Export the full graph for external graph/table tools."""
    graph = rebuild_graph_from_documents(user.id)
    detailed = graph.export_detailed()
    export_format = format.lower()

    if export_format == "json":
        return JSONResponse(
            content=_to_cytoscape_json(detailed),
            headers={"Content-Disposition": 'attachment; filename="graphmind-graph.json"'},
        )
    if export_format == "gexf":
        return Response(
            content=_to_gexf(detailed),
            media_type="application/gexf+xml",
            headers={"Content-Disposition": 'attachment; filename="graphmind-graph.gexf"'},
        )
    if export_format == "csv":
        return Response(
            content=_to_csv(detailed),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="graphmind-graph.csv"'},
        )

    raise HTTPException(status_code=400, detail="Unsupported graph export format")


def rebuild_graph_from_documents(user_id: Optional[str] = None) -> KnowledgeGraph:
    """Build a fresh in-memory graph from stored files and cached parses."""
    graph = knowledge_graph
    graph.clear()

    for metadata in document_service.list_documents(user_id):
        filename = metadata["filename"]
        original_name = metadata.get("original_filename", filename)
        parsed = get_cached_parse(filename)
        if not parsed:
            try:
                parsed = parse_document_file(filename, metadata["file_path"], original_name)
            except (OSError, ValueError, RuntimeError) as exc:
                # One bad upload should not blank the whole graph. Log it so
                # the skipped file is visible during local debugging.
                log.warning("Skipping %s while rebuilding graph: %s", original_name, exc)
                continue

        try:
            entities = entity_extractor.extract_from_parsed_document(parsed)
            relations = entity_extractor.extract_relations(entities, parsed.get("content", ""))
            graph.add_document(original_name, entities, relations, document_id=f"doc:{filename}")
        except (KeyError, TypeError, ValueError) as exc:
            # Entity extraction is still evolving, so keep the graph panel
            # resilient while making malformed parser output visible.
            log.warning("Skipping graph extraction for %s: %s", original_name, exc)

    return graph


def _to_cytoscape_json(graph: dict) -> dict:
    """Cytoscape.js accepts nodes and edges under elements.*.data."""
    nodes = [
        {
            "data": {
                "id": node["id"],
                "label": node["label"],
                "type": node["type"],
                "confidence": node.get("confidence", 1.0),
                "sources": node.get("sources", []),
                **node.get("properties", {}),
            }
        }
        for node in graph.get("nodes", [])
    ]
    edges = [
        {
            "data": {
                "id": f"{edge['source']}->{edge['target']}:{edge['type']}",
                "source": edge["source"],
                "target": edge["target"],
                "label": edge["type"],
                "type": edge["type"],
                "weight": edge.get("weight", 1),
                "confidence": edge.get("confidence", 1.0),
                "sources": edge.get("sources", []),
            }
        }
        for edge in graph.get("edges", [])
    ]
    return {"format": "cytoscape", "elements": {"nodes": nodes, "edges": edges}}


def _to_gexf(graph: dict) -> str:
    """GEXF is useful for Gephi and other desktop graph tools."""
    ns = "http://www.gexf.net/1.2draft"
    ElementTree.register_namespace("", ns)
    root = ElementTree.Element(f"{{{ns}}}gexf", {"version": "1.2"})
    graph_el = ElementTree.SubElement(root, f"{{{ns}}}graph", {"mode": "static", "defaultedgetype": "directed"})
    node_attrs = ElementTree.SubElement(graph_el, f"{{{ns}}}attributes", {"class": "node"})
    edge_attrs = ElementTree.SubElement(graph_el, f"{{{ns}}}attributes", {"class": "edge"})
    for attr_id, title in (("type", "type"), ("confidence", "confidence"), ("sources", "sources")):
        ElementTree.SubElement(node_attrs, f"{{{ns}}}attribute", {"id": attr_id, "title": title, "type": "string"})
        ElementTree.SubElement(edge_attrs, f"{{{ns}}}attribute", {"id": attr_id, "title": title, "type": "string"})
    nodes_el = ElementTree.SubElement(graph_el, f"{{{ns}}}nodes")
    edges_el = ElementTree.SubElement(graph_el, f"{{{ns}}}edges")

    for node in graph.get("nodes", []):
        node_el = ElementTree.SubElement(
            nodes_el,
            f"{{{ns}}}node",
            {"id": node["id"], "label": node["label"]},
        )
        attvalues = ElementTree.SubElement(node_el, f"{{{ns}}}attvalues")
        _gexf_att(attvalues, "type", node.get("type", "ENTITY"), ns)
        _gexf_att(attvalues, "confidence", node.get("confidence", 1.0), ns)
        _gexf_att(attvalues, "sources", ", ".join(node.get("sources", [])), ns)

    for index, edge in enumerate(graph.get("edges", [])):
        edge_el = ElementTree.SubElement(
            edges_el,
            f"{{{ns}}}edge",
            {
                "id": str(index),
                "source": edge["source"],
                "target": edge["target"],
                "label": edge.get("type", "RELATED_TO"),
                "weight": str(edge.get("weight", 1)),
            },
        )
        attvalues = ElementTree.SubElement(edge_el, f"{{{ns}}}attvalues")
        _gexf_att(attvalues, "type", edge.get("type", "RELATED_TO"), ns)
        _gexf_att(attvalues, "confidence", edge.get("confidence", 1.0), ns)
        _gexf_att(attvalues, "sources", ", ".join(edge.get("sources", [])), ns)

    return ElementTree.tostring(root, encoding="unicode", xml_declaration=True)


def _gexf_att(parent: ElementTree.Element, name: str, value: object, ns: str) -> None:
    ElementTree.SubElement(parent, f"{{{ns}}}attvalue", {"for": name, "value": str(value)})


def _to_csv(graph: dict) -> str:
    """Single-table CSV keeps exports simple for spreadsheet tools."""
    output = StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "kind",
            "id",
            "label",
            "type",
            "source",
            "target",
            "weight",
            "confidence",
            "sources",
        ],
    )
    writer.writeheader()
    for node in graph.get("nodes", []):
        writer.writerow({
            "kind": "node",
            "id": node.get("id", ""),
            "label": node.get("label", ""),
            "type": node.get("type", ""),
            "source": "",
            "target": "",
            "weight": "",
            "confidence": node.get("confidence", ""),
            "sources": "; ".join(node.get("sources", [])),
        })
    for edge in graph.get("edges", []):
        writer.writerow({
            "kind": "edge",
            "id": f"{edge.get('source', '')}->{edge.get('target', '')}:{edge.get('type', '')}",
            "label": edge.get("type", ""),
            "type": edge.get("type", ""),
            "source": edge.get("source", ""),
            "target": edge.get("target", ""),
            "weight": edge.get("weight", ""),
            "confidence": edge.get("confidence", ""),
            "sources": "; ".join(edge.get("sources", [])),
        })
    return output.getvalue()
