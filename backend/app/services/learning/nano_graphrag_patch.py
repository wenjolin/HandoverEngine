"""Replace nano-graphrag graspologic clustering with networkx (Python 3.14 friendly)."""

from __future__ import annotations

import html
from collections import defaultdict
from typing import cast

import networkx as nx
from networkx.algorithms.community import louvain_communities


def apply_networkx_clustering_patch() -> None:
    from nano_graphrag._storage.gdb_networkx import NetworkXStorage

    @staticmethod
    def stable_largest_connected_component(graph: nx.Graph) -> nx.Graph:
        if graph.number_of_nodes() == 0:
            return graph
        if nx.is_directed(graph):
            components = nx.weakly_connected_components(graph)
        else:
            components = nx.connected_components(graph)
        largest = max(components, key=len)
        subgraph = cast(nx.Graph, graph.subgraph(largest).copy())
        node_mapping = {
            node: html.unescape(str(node).upper().strip()) for node in subgraph.nodes()
        }
        subgraph = nx.relabel_nodes(subgraph, node_mapping)
        return NetworkXStorage._stabilize_graph(subgraph)

    async def _leiden_clustering(self) -> None:
        graph = NetworkXStorage.stable_largest_connected_component(self._graph)
        if graph.number_of_nodes() == 0:
            self._cluster_data_to_subgraphs({})
            return
        communities = louvain_communities(
            graph,
            seed=int(self.global_config.get("graph_cluster_seed") or 0),
        )
        node_communities: dict[str, list[dict[str, int]]] = defaultdict(list)
        for cluster_id, nodes in enumerate(communities):
            for node in nodes:
                node_communities[node].append({"level": 0, "cluster": cluster_id})
        self._cluster_data_to_subgraphs(dict(node_communities))

    NetworkXStorage.stable_largest_connected_component = (  # type: ignore[method-assign]
        stable_largest_connected_component
    )
    NetworkXStorage._leiden_clustering = _leiden_clustering  # type: ignore[method-assign]
