# from codeviews.CFG.CFG_python import CFGGraph_python
from .CFG_csharp import CFGGraph_csharp
from .CFG_java import CFGGraph_java
from ...tree_parser.parser_driver import ParserDriver
import networkx as nx
from ...utils.timeout import timeout_function
from  networkx.classes.multidigraph import MultiDiGraph

def to_networkx_simple(edge_list):
    G = nx.MultiDiGraph()
    for edge in edge_list:
        if edge[0] != edge[1]:
            G.add_edge(edge[0], edge[1])
    return G


def find_paths(G, source, target):
    visited = {edge: False for edge in G.edges()}
    queue = []
    paths = []
    queue.append([source])
    while len(queue):
        for i in range(len(queue)):
            current_path = queue.pop(0)
            for next_node in G.successors(current_path[-1]):
                next_path = current_path.copy()
                next_path.append(next_node)

                if next_node is target:
                    new_edges = []
                    for j in range(len(next_path) - 1):
                        if not visited[(next_path[j], next_path[j + 1])]:
                            new_edges.append((next_path[j], next_path[j + 1]))
                            visited[(next_path[j], next_path[j + 1])] = True
                    if len(new_edges):
                        paths.append(next_path)

                    if all([visited[edge] for edge in visited.keys()]):
                        return paths
                else:
                    queue.append(next_path)

    return paths


def identify_independent_paths(edges, paths):
    visited = {edge: False for edge in edges}
    independent_paths = []
    for path in paths:
        path_edges = [(path[i], path[i + 1]) for i in range(len(path) - 1)]
        unique_edges = []
        for edge in path_edges:
            if not visited.get(edge):
                unique_edges.append(edge)
                visited[edge] = True
        if len(unique_edges):
            independent_paths.append(path)
    return independent_paths


def calculate_cyclomatic_complexity(cfg: MultiDiGraph):
    cyclomatic_complexity = cfg.number_of_edges() - cfg.number_of_nodes() + 2
    return cyclomatic_complexity


class CFGDriver:
    def __init__(
            self,
            src_language="java",
            src_code="",
            properties={},
    ):
        self.src_language = src_language

        self.parser = ParserDriver(src_language, src_code).parser
        self.root_node = self.parser.root_node
        self.src_code = self.parser.src_code
        self.properties = properties
        self.dummy_exit = 2
        self.CFG_map = {
            "java": CFGGraph_java,
            "cs": CFGGraph_csharp,
            # "python": CFGGraph_python
        }

        self.CFG = self.CFG_map[self.src_language](
            self.src_language,
            self.src_code,
            self.properties,
            self.root_node,
            self.parser,
        )

        self.graph = self.CFG.graph
        self.node_type_map = {key[0][0]: key[2] for key in self.CFG.node_list.keys()}

        self.CFG_nodes = self.CFG.CFG_node_list
        self.CFG_node_ids = [node[0] for node in self.CFG_nodes]
        self.CFG_node_map = {node[0]: (node[2], self.node_type_map.get(node[1])) for node in self.CFG_nodes}
        self.CFG_edge_map = {(edge[0], edge[1]): edge[2] for edge in self.CFG.CFG_edge_list}

        self.return_statement_map = self.CFG.records["return_statement_map"]
        self.basic_blocks = self.CFG.records["basic_blocks"]
        # class declarations in the class file
        self.class_list = self.CFG.records["class_list"]
        # method declaration inside the class file
        self.method_declarations = {y: x for x, y in self.CFG.records["method_list"].items()
                                    if x[0][0] in self.class_list.keys()}
        self.methods_under_test, self.testable_methods = self.filter_method_under_tests()

        self.edge_label_map = {
            "neg_next": False,
            "pos_next": True,
            "sync_next": "after synchronized",
            "next_line 2": "after if block",
            "next_line 3": "after empty if",
            "next_line 4": "after alternative block",
            "next_line 5": "after empty alternative block",
            "next_line 6": False,
            "next_line 7": "next switch case"
        }

        self.file_obj = self.generate_file_obj()

    def generate_file_obj(self):
        f_obj = {"imports": [], "class_objects": []}
        import_start_id = len(self.CFG_node_ids)
        for clz_name, clz_id in self.class_list.items():
            clz_node = self.CFG_node_map[clz_id][0]
            idx_1 = self.CFG_node_ids.index(clz_id)
            import_start_id = min(idx_1, import_start_id)
            idx_2 = self.CFG_node_ids.index(max(self.return_statement_map[clz_id]))

            fields = [{"id": node, "value": self.CFG_node_map[node][0]} for node in self.CFG_node_ids[idx_1: idx_2 + 1]
                      if self.CFG_node_map[node][1] == "field_declaration"]
            constructors = [{"id": node, "value": self.CFG_node_map[node][0]} for node in
                            self.CFG_node_ids[idx_1: idx_2 + 1]
                            if self.CFG_node_map[node][1] == "constructor_declaration"]

            clz_obj = {"class_declaration": {"id": clz_id, "value": clz_node, "name": clz_name}, "fields": fields,
                       "constructors": constructors, "methods_under_test": []}

            for method in self.methods_under_test:
                # skip method without complex control flow statements
                # if method[4] > 1:
                if "test_code" in self.properties.keys() or "statistics" in self.properties.keys():
                    source_id = method[0]
                    method_obj = {"method_declaration": {"id": source_id, "value": self.CFG_node_map[source_id][0]}}
                    clz_obj["methods_under_test"].append(method_obj)
                else:
                    if method[5] == clz_name and "private" not in clz_node:
                        method_obj = self.control_flow_analysis_for_method(method)
                        clz_obj["methods_under_test"].append(method_obj)

            f_obj["class_objects"].append(clz_obj)

        imports = [{"id": node, "value": self.CFG_node_map[node][0]} for node in self.CFG_node_ids[: import_start_id]
                   if self.CFG_node_map[node][1] == "import_declaration"]
        f_obj["imports"] = imports
        return f_obj

    def control_flow_analysis_for_method(self, method) -> dict:
        """
        control flow analysis for a method under test to extract paths
        :param method: method is a tuple (start_id, last_node_id, method_graph, method_name, cyc_complexity, clz_name)
        :return:
        """
        method_calls = self.get_method_calls_for_each_statement()
        method_decls = [(x, y[0][1], y[1]) for x, y in self.method_declarations.items()]
        sorted_method_decls = sorted(method_decls, key=lambda x: x[0])
        # print(sorted_method_decls)
        source_id = method[0]
        last_id = method[1]
        sub_graph = method[2]
        node_ids = self.CFG_node_ids[self.CFG_node_ids.index(source_id): self.CFG_node_ids.index(last_id) + 1]

        method_obj = {"method_declaration": {"id": source_id, "nodes": node_ids,
                                             "value": self.CFG_node_map[source_id][0], "name": method[3],
                                             "complexity": method[4]}, "paths": []}
        paths = timeout_function(5, find_paths, sub_graph, source_id, target=self.dummy_exit)
        if not len(paths):
            print(method[5], method[3], method[2].edges())
        edges = [e for e in sub_graph.edges()]
        independent_paths = identify_independent_paths(edges, paths)

        for index, path in enumerate(independent_paths):
            path_arr = []
            true_blocks = []
            # false_branches = []
            catch_at = None
            inside_calls = set()
            outside_calls = set()
            path_edges = [(path[i], path[i + 1]) for i in range(len(path) - 1)]
            for edge in path_edges[1: len(path_edges) - 1]:
                edge_label = self.CFG_edge_map.get(edge)
                node_label = self.CFG_node_map.get(edge[0])[0]
                stat_str = {"id": edge[0], "statement": node_label, "conditional": None}

                if method_calls["inside"].get(edge[0]):
                    mthds = []
                    for m in method_calls["inside"].get(edge[0]):
                        for idx, item in enumerate(sorted_method_decls):
                            if item[1] == m[1]:
                                next_node_id = sorted_method_decls[idx + 1][0] if idx < len(sorted_method_decls) - 1 \
                                    else None
                                mthds.append(f"{m[0]}, {item[0]}, {next_node_id}")

                    inside_calls.update(mthds)

                if method_calls["outside"].get(edge[0]):
                    methods = [m[0] for m in method_calls["outside"].get(edge[0])]
                    outside_calls.update(methods)

                if edge_label == "pos_next":
                    node = edge[1]
                    block_nodes = []
                    for idx, block in self.basic_blocks.items():
                        if node in block:
                            block_nodes = block
                            break

                    block = [{"id": node_id, "statement": self.CFG_node_map.get(node_id)[0]} for node_id in block_nodes]
                    true_blocks.append(
                        {"true_condition": {"id": edge[0], "statement": node_label}, "basic_block": block})
                    edge_label = self.edge_label_map.get(edge_label)
                    stat_str["conditional"] = edge_label
                elif edge_label == "neg_next" or edge_label == "next_line 6":
                    # false_branches.append(node_label)
                    edge_label = self.edge_label_map.get(edge_label)
                    stat_str["conditional"] = edge_label
                elif edge_label == "catch_exception":
                    if (edge[0] in method_calls["outside"].keys()) or \
                            (edge[0] in method_calls["inside"]):
                        catch_at = node_label
                else:
                    edge_label = self.edge_label_map.get(edge_label)
                    if edge_label is not None:
                        stat_str["conditional"] = edge_label

                path_arr.append(stat_str)

            last_node_id = path_edges[-1][0]
            path_arr.append({"id": last_node_id, "statement": self.CFG_node_map.get(last_node_id)[0],
                             "conditional": None})
            if method_calls["inside"].get(last_node_id):
                mthds = []
                for m in method_calls["inside"].get(last_node_id):
                    for idx, item in enumerate(sorted_method_decls):
                        if item[1] == m[1]:
                            next_node_id = sorted_method_decls[idx + 1][0] if idx < len(sorted_method_decls) - 1 \
                                else None
                            mthds.append(f"{m[0]}, {item[0]}, {next_node_id}")
                inside_calls.update(mthds)
            if method_calls["outside"].get(last_node_id):
                methods = [m[0] for m in method_calls["outside"].get(last_node_id)]
                outside_calls.update(methods)
            method_obj["paths"].append(
                {"path": path_arr, "true_branches": true_blocks,
                 "catch_exception_at": catch_at,
                 "method_calls_within_class": list(inside_calls),
                 "method_calls_outside_class": list(outside_calls)})
        return method_obj

    def get_method_calls_for_each_statement(self):
        method_calls = {"outside": {}, "inside": {}}
        method_calls_outside = {x: y for x, y in self.CFG.records["function_calls"].items()
                                if x[0][0] not in self.class_list.keys()}
        for x, y in method_calls_outside.items():
            x_str = '.'.join(x[0]) + "(" + ', '.join(x[1]) + ")".strip()
            x_tuple = (x_str, x[0][1], x[1])
            for item in y:
                if item[1] in method_calls["outside"].keys():
                    method_calls["outside"][item[1]].append(x_tuple)
                else:
                    method_calls["outside"][item[1]] = [x_tuple]

        method_calls_inside = {x: y for x, y in self.CFG.records["function_calls"].items()
                               if x[0][0] in self.class_list.keys()}
        for x, y in method_calls_inside.items():
            x_str = '.'.join(x[0]) + "(" + ', '.join(x[1]) + ")".strip()
            x_tuple = (x_str, x[0][1], x[1])
            for item in y:
                if item[1] in method_calls["inside"].keys():
                    method_calls["inside"][item[1]].append(x_tuple)
                else:
                    method_calls["inside"][item[1]] = [x_tuple]
        # print(method_calls["inside"])
        return method_calls

    def filter_method_under_tests(self):
        methods_under_test = []
        testable_methods_statistics = {"=1": {}, "2-10": {}, "11-20": {}, ">20": {}, "to_be_determined": {}}
        for index, node in enumerate(self.CFG_nodes):
            if self.src_language == "java" and node[3] == "method_declaration":
                start_id = node[0]
                if "test_code" in self.properties.keys():
                    # test method are public methods or default access
                    if not (node[2].strip().startswith("private") or node[2].strip().startswith("protected")):
                        last_node_id = max(self.return_statement_map[start_id])
                        method_obj = (start_id, last_node_id, None, None, 1, None)
                        methods_under_test.append(method_obj)
                else:
                    # methods are public, protected or default access
                    if not node[2].strip().startswith("private"):
                        meth_decl = self.method_declarations.get(start_id)
                        if meth_decl:
                            clz_name = meth_decl[0][0]
                            method_name = meth_decl[0][1]
                            parameters = meth_decl[1]
                            last_node_id = max(self.return_statement_map[start_id])
                            method_nodes = self.get_method_nodes(start_id)
                            method_block_length = len(method_nodes) - 1

                            # boolean getter
                            if method_name.startswith("is") and "boolean" in node[2] and len(parameters) == 0:
                                continue
                            # setter
                            if method_name.startswith("set") and "void" in node[2] and len(parameters) == 1 \
                                    and method_block_length == 1:
                                continue
                            # getter
                            if method_name.startswith("get") and len(parameters) == 0 and method_block_length == 1:
                                continue

                            # methods with empty body
                            if method_block_length <= 0:
                                continue
                            # main method
                            if method_name == "main" and "static" in node[2] and "void" in node[2]:
                                continue
                            method_full_name = '.'.join(meth_decl[0]) + "(" + ', '.join(meth_decl[1]) + ")"

                            # limiting cyclomatic complexity to 10 (Structured Testing:
                            # A Testing Methodology Using the Cyclomatic Complexity Metric)
                            end_nodes = set(self.return_statement_map[start_id])
                            method_graph = self.generate_method_control_flow_graph(method_nodes, end_nodes, start_id)

                            cyc_complexity = calculate_cyclomatic_complexity(method_graph)
                            method_obj = (start_id, last_node_id, method_graph, method_name, cyc_complexity, clz_name)
                            if cyc_complexity > 0:
                                methods_under_test.append(method_obj)

                            if "statistics" in self.properties.keys():
                                if cyc_complexity > 0:
                                    paths = timeout_function(5, find_paths, method_graph, start_id, target=self.dummy_exit)
                                    edges = [e for e in method_graph.edges()]
                                    independent_paths = identify_independent_paths(edges, paths)

                                    if not len(paths):
                                        with open("debug.txt", "a") as f:
                                            f.write(f" time out: {self.properties['statistics']}: {method_name}\n")
                                    elif len(paths) != cyc_complexity:
                                        with open("debug.txt", "a") as f:
                                            f.write(f" not equal: {self.properties['statistics']}: {method_name}\n")

                                    if cyc_complexity == 1:
                                        testable_methods_statistics["=1"][method_full_name] = [cyc_complexity, len(paths),
                                                                                               len(independent_paths)]
                                    if 2 <= cyc_complexity <= 10:
                                        testable_methods_statistics["2-10"][method_full_name] = [cyc_complexity, len(paths),
                                                                                                 len(independent_paths)]
                                    if 11 <= cyc_complexity <= 20:
                                        testable_methods_statistics["11-20"][method_full_name] = [cyc_complexity,
                                                                                                  len(paths),
                                                                                                  len(independent_paths)]
                                    if cyc_complexity > 20:
                                        testable_methods_statistics[">20"][method_full_name] = [cyc_complexity, len(paths),
                                                                                                len(independent_paths)]
                                else:
                                    testable_methods_statistics["to_be_determined"][method_full_name] = cyc_complexity

        return methods_under_test, testable_methods_statistics

    def get_loop_nodes(self, method_nodes):
        loop_nodes = []
        for n_id in method_nodes:
            node_type = self.CFG_node_map.get(n_id)[1]
            if node_type in self.CFG.statement_types["loop_control_statement"]:
                loop_nodes.append(n_id)

    def generate_method_control_flow_graph(self, node_ids, return_nodes, start_id):

        edges = [edge for edge in self.CFG_edge_map.keys() if edge[0] in node_ids and edge[1] in node_ids]

        method_graph = to_networkx_simple(edges)
        end_nodes = set()
        end_nodes.update(return_nodes)

        for node_id in end_nodes:
            method_graph.add_edge(node_id, self.dummy_exit)

        # handle the case when there is a method declaration inside method (old feature before lambda)
        # handle throw statement by connecting it to the exit node.
        unreachable_nodes = self.check_graph_connected(method_graph, end_nodes, start_id)
        throw_statements = [node[0] for node in unreachable_nodes if node[1] == "throw_statement" and node[2] == "out"]
        inner_methods = [node[0] for node in unreachable_nodes if node[1] == "method_declaration" and node[2] == "in"]
        inner_returns = [node[0] for node in unreachable_nodes if node[1] == "return_statement" and node[2] == "out"]

        for node_id in throw_statements:
             method_graph.add_edge(node_id, self.dummy_exit)
        for node_id in inner_methods:
            # inner method
            node_index = self.CFG_node_ids.index(node_id)
            parent_node = self.CFG_node_ids[node_index - 1]
            method_graph.add_edge(parent_node, node_id)
            return_stats = self.return_statement_map[node_id]
            for nid in return_stats:
                if nid in inner_returns:
                    method_graph.add_edge(nid, parent_node)

        return method_graph

    def check_graph_connected(self, method_graph, return_nodes, start_node):
        unreachable_nodes = []
        for node in method_graph.nodes():
            if node != start_node and method_graph.in_degree(node) == 0:
                node_type = self.CFG_node_map[node][1]
                unreachable_nodes.append((node, node_type, "in"))
            if node not in return_nodes and node != self.dummy_exit and method_graph.out_degree(node) == 0:
                node_type = self.CFG_node_map[node][1]
                unreachable_nodes.append((node, node_type, "out"))

        return unreachable_nodes

    def get_method_nodes(self, start_node):
        start_node_index = self.CFG_node_ids.index(start_node)
        last_node_id = max(self.return_statement_map[start_node])
        last_node_index = self.CFG_node_ids.index(last_node_id)
        method_nodes = self.CFG_node_ids[start_node_index: last_node_index + 1]
        return method_nodes

