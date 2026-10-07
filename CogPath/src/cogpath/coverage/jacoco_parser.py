import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup


def read_html_file(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()


def parse_method_with_missed_lines(project_dir: str, package_name: str, class_name: str) -> list[tuple]:
    """
    parse jacoco.xml to identify methods with start line number
    :param project_dir: eg. "org.apache.commons.cli"
    :param package_name: eg. "PatternOptionBuilder"
    :param class_name: eg. "../../defects4j-sample/Cli-40f"
    :return: list[(method: start_line)]
    """

    coverage_report_path = f"{project_dir}/target/jacoco/jacoco.xml"
    tree = ET.parse(coverage_report_path)
    root = tree.getroot()
    package_element, class_element = None, None
    methods_with_missed_lines = []
    for child in root:
        if child.tag == "package" and ".".join(child.attrib['name'].split('/')) == package_name:
            package_element = child
    for child in package_element:
        if child.tag == "class" and child.attrib['name'].split('/')[-1] == class_name:
            class_element = child
    for method in class_element.findall('method'):
        if int(method.find("counter[@type='LINE']").get('missed')):
            methods_with_missed_lines.append((method.get('name'), int(method.get('line'))))

    return methods_with_missed_lines


def parse_method_with_missed_branches(project_dir: str, package_name: str, class_name: str) -> list[tuple]:
    """
    parse jacoco.xml to identify methods with start line number
    :param project_dir: eg. "org.apache.commons.cli"
    :param package_name: eg. "PatternOptionBuilder"
    :param class_name: eg. "../../defects4j-sample/Cli-40f"
    :return: list[(method: start_line)]
    """

    coverage_report_path = f"{project_dir}/target/jacoco/jacoco.xml"
    tree = ET.parse(coverage_report_path)
    root = tree.getroot()
    package_element, class_element = None, None
    methods_with_missed_branches = []
    for child in root:
        if child.tag == "package" and ".".join(child.attrib['name'].split('/')) == package_name:
            package_element = child
    for child in package_element:
        if child.tag == "class" and child.attrib['name'].split('/')[-1] == class_name:
            class_element = child
    for method in class_element.findall('method'):
        if method.find("counter[@type='BRANCH']"):
            missed_branches = int(method.find("counter[@type='BRANCH']").get('missed'))
            if missed_branches:
                methods_with_missed_branches.append((method.get('name'), int(method.get('line'))))

    return methods_with_missed_branches


def parse_missed_line_branch_locations(project_dir: str, package_name: str, class_name: str):
    """
    parse {package_name}/{class_name}.java.html to identify missed lines/branches
    :param project_dir:
    :param package_name:
    :param class_name:
    :return:
    """
    coverage = {}
    html_file = f"{project_dir}/target/jacoco/{package_name}/{class_name}.java.html"
    html_content = read_html_file(html_file)
    soup = BeautifulSoup(html_content, 'html.parser')

    elements_with_bnc_class = soup.find_all(class_='nc bnc')
    bnc_ids = [int(element.get('id').strip('L')) for element in elements_with_bnc_class if element.get('id')]
    coverage["branch_not_covered"] = bnc_ids

    elements_with_bpc_class = soup.find_all(class_='pc bpc')
    bpc_ids = [int(element.get('id').strip('L')) for element in elements_with_bpc_class if element.get('id')]
    coverage["branch_partially_covered"] = bpc_ids

    elements_with_nc_class = soup.find_all(class_='nc')
    nc_ids = [int(element.get('id').strip('L')) for element in elements_with_nc_class if element.get('id')]
    coverage["lines_not_covered"] = nc_ids

    elements_with_pc_class = soup.find_all(class_='pc')
    pc_ids = [int(element.get('id').strip('L')) for element in elements_with_pc_class if element.get('id')]
    coverage["lines_partially_covered"] = pc_ids

    elements_with_fc_class = soup.find_all(class_='fc')
    fc_ids = [int(element.get('id').strip('L')) for element in elements_with_fc_class if element.get('id')]
    coverage["lines_fully_covered"] = fc_ids
    return coverage
