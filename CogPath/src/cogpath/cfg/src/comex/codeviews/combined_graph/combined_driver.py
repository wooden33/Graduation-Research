import json
import networkx as nx

from ..CFG.CFG_driver import CFGDriver
from ...utils import postprocessor, preprocessor


def preprocessed_to_original_line_number_mapping(original, lang="java"):

    p_to_o = {}
    o_to_p = {}
    idx = 0
    for i, line in enumerate(original.split("\n")):
        is_comment = preprocessor.is_comment(lang, line)
        if not is_comment:
            idx += 1
            o_to_p[i + 1] = idx
            p_to_o[idx] = i + 1
    return p_to_o, o_to_p


def preprocessed_line_number_and_node_id_mapping(node_list):
    # each node is a tuple (node_id, line_index, node_str, node_type, block_index)
    line_to_id = {}
    id_to_line = {}
    for node in node_list:
        node_str = node[2]
        index = node[1]
        node_id = node[0]

        # for the case a node in multiple lines
        # line number equals to index + 1
        lines = len(node_str.split("\n"))
        for i in range(lines):
            line_to_id[index + 1 + i] = node_id
            if node_id not in id_to_line:
                id_to_line[node_id] = [index + 1 + i]
            else:
                id_to_line[node_id].append(index + 1 + i)

    return line_to_id, id_to_line


def line_number_to_node_id_mapping(src_code, node_list):
    processed_to_original_mapping, original_to_processed_mapping = \
        preprocessed_to_original_line_number_mapping(src_code)

    processed_line_to_id, id_to_processed_line = preprocessed_line_number_and_node_id_mapping(node_list)

    # key: original_line_number, value: tuple (preprocessed_line_number, node_id)
    line_number_to_node_id = {processed_to_original_mapping[k]: (k, v) for k, v in processed_line_to_id.items()
                              if k in processed_to_original_mapping}

    # key: node_id, value: list of [original lines]
    node_id_to_line_number = {}
    for node_id, lines in id_to_processed_line.items():
        original_lines = [processed_to_original_mapping[line] for line in lines if
                          line in processed_to_original_mapping]
        if original_lines:
            node_id_to_line_number[node_id] = original_lines

    return line_number_to_node_id, node_id_to_line_number


class CombinedDriver:
    def __init__(
            self,
            src_language="java",
            src_code="",
            output_file="output.json",
    ):
        self.src_language = src_language
        self.src_code = src_code
        self.graph = nx.MultiDiGraph()

        self.driver = CFGDriver(
            self.src_language, self.src_code
        )

        self.graph = self.driver.graph

        self.node_list = self.driver.CFG_nodes

        # self.json = postprocessor.write_networkx_to_json(
        #     self.graph, output_file
        # )

        self.file_obj = self.driver.file_obj

        self.preprocessed_src_code = self.driver.src_code

        self.line_number_to_node_id, self.node_id_to_line_number = \
            line_number_to_node_id_mapping(self.src_code, self.node_list)

        self.testable_methods_statistics = self.driver.testable_methods

        # with open(f"{'-'.join(self.driver.class_list)}-cfa.json", "w") as outfile:
        #     json.dump(self.file_obj, outfile)

        # with open("preprocessed.java", "w") as f:
        #     f.write(self.preprocessed_src_code)
