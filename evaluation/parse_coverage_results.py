"""
Parse coverage results and generate statistics.
Supports configurable paths via command line arguments.
"""
import argparse
import csv
import os
import re


def parse_coverage_from_html(html_content):
    """Parse HTML to extract coverage data for all iterations using regex."""
    # Clean up HTML content
    html_content = html_content.strip()

    # Find all rows - match from <tr> to </tr> using regex
    # This handles malformed HTML with unclosed pre/code tags
    row_pattern = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL)
    rows = row_pattern.findall(html_content)

    coverage_data = {}

    for row in rows:
        # Find all cells in this row
        cell_pattern = re.compile(r'<td[^>]*>(.*?)</td>', re.DOTALL)
        cells = cell_pattern.findall(row)

        if len(cells) < 6:
            continue

        # Extract status from first cell (may contain class attribute)
        status_cell = cells[0]
        status_match = re.search(r'status-(\w+)', status_cell)
        status = status_match.group(1) if status_match else cells[0].strip()
        if status == 'INFO':
            status = 'INFO'
        elif status == 'PASS':
            status = 'PASS'
        elif status == 'FAIL':
            status = 'FAIL'
        else:
            # Try to get text content
            status = re.sub(r'<[^>]+>', '', status_cell).strip()

        # Extract label from second cell
        label = re.sub(r'<[^>]+>', '', cells[1]).strip()

        # Extract coverage values (columns 4 and 5 are line and branch coverage)
        try:
            line_coverage = float(re.sub(r'<[^>]+>', '', cells[4]).strip())
            branch_coverage = float(re.sub(r'<[^>]+>', '', cells[5]).strip())
        except (ValueError, IndexError):
            continue

        # For g_X iterations, only keep entries with status=INFO (aggregated results)
        if label.startswith('g_') and status != 'INFO':
            continue

        # Handle empty label rows with INFO status (final results)
        if not label and status == 'INFO':
            coverage_data['final'] = {
                "line_coverage": line_coverage,
                "branch_coverage": branch_coverage
            }
            continue

        # Skip empty label rows that are not INFO
        if not label:
            continue

        coverage_data[label] = {
            "line_coverage": line_coverage,
            "branch_coverage": branch_coverage
        }

    return coverage_data


def load_complexity_data(csv_path):
    """Load cyclomatic complexity data from class_list.csv."""
    complexity = {}
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            key = f"{row['project']}-{row['class']}"
            complexity[key] = int(row['complexity'])
    return complexity


def get_project_from_filename(filename, prompt_type="control"):
    """Extract class name from filename."""
    # Try format: ClassName_control_ClassName_control_test_results.html
    match = re.match(rf'^(.+?)_{prompt_type}_{prompt_type}_test_results\.html$', filename)
    if match:
        return match.group(1)
    # Try format: ClassName_control_test_results.html
    match = re.match(rf'^(.+?)_{prompt_type}_test_results\.html$', filename)
    if match:
        return match.group(1)
    return None


def main():
    parser = argparse.ArgumentParser(description='Parse coverage results and generate statistics.')
    parser.add_argument('--result-dir', type=str, required=True,
                        help='Directory containing HTML result files')
    parser.add_argument('--class-list', type=str, required=True,
                        help='Path to class_list.csv with complexity data')
    parser.add_argument('--output', type=str, default='coverage_statistics.csv',
                        help='Output CSV file path (default: coverage_statistics.csv)')
    parser.add_argument('--prompt-type', type=str, default='control',
                        help='Prompt type used in filenames (default: control)')
    parser.add_argument('--max-iterations', type=int, default=8,
                        help='Maximum number of iterations to extract (default: 8)')

    args = parser.parse_args()

    # Load complexity data
    complexity_data = load_complexity_data(args.class_list)

    # Find all HTML files
    html_files = [f for f in os.listdir(args.result_dir) if f.endswith('.html')]

    results = []

    for html_file in sorted(html_files):
        class_name = get_project_from_filename(html_file, args.prompt_type)
        if not class_name:
            continue

        # Determine project from complexity data
        project = None
        complexity = None
        for key, cc in complexity_data.items():
            if key.endswith(f"-{class_name}"):
                project = key.split('-')[0]
                complexity = cc
                break

        if complexity is None:
            print(f"Warning: No complexity found for {class_name}")
            continue

        # Parse HTML
        html_path = os.path.join(args.result_dir, html_file)
        try:
            with open(html_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            coverage_data = parse_coverage_from_html(html_content)
        except Exception as e:
            print(f"Error parsing {html_file}: {e}")
            continue

        # Find final iteration (last g_X entry)
        # First check if there's a 'final' entry (empty label INFO row)
        final = coverage_data.get('final', {})
        final_label = 'final' if final else None
        max_iter = -1

        # If no 'final' entry, find the last g_X entry
        if not final:
            for label in coverage_data.keys():
                match = re.match(r'^g_(\d+)$', label)
                if match:
                    iter_num = int(match.group(1))
                    if iter_num > max_iter:
                        max_iter = iter_num
                        final_label = label
            final = coverage_data.get(final_label, {})
        else:
            # If we have a 'final' entry, find max_iter from g_X entries
            for label in coverage_data.keys():
                match = re.match(r'^g_(\d+)$', label)
                if match:
                    iter_num = int(match.group(1))
                    if iter_num > max_iter:
                        max_iter = iter_num

        # Get final values for filling
        final_line = final.get('line_coverage') if final else 0
        final_branch = final.get('branch_coverage') if final else 0

        # Extract coverage for multiple iterations (g_0 to g_7 by default)
        # Fill missing iterations with final values
        iter_data = {}
        for i in range(args.max_iterations):
            g_data = coverage_data.get(f'g_{i}', {})
            line_val = g_data.get('line_coverage')
            branch_val = g_data.get('branch_coverage')

            # Fill missing with final values (always, to get complete coverage curve)
            # This means if a class stopped at g_2, g_3-g_7 will all be filled with final value
            if line_val is None:
                line_val = final_line if final_line else 0
            if branch_val is None:
                branch_val = final_branch if final_branch else 0

            iter_data[f'iter_{i}_line'] = line_val
            iter_data[f'iter_{i}_branch'] = branch_val

        # Build result row with dynamic iteration fields
        result_row = {
            'project': project,
            'class': class_name,
            'complexity': complexity,
            'final_line': final.get('line_coverage'),
            'final_branch': final.get('branch_coverage'),
            'final_iter': max_iter
        }
        # Add iteration data
        result_row.update(iter_data)
        results.append(result_row)

    # Build fieldnames dynamically
    fieldnames = ['project', 'class', 'complexity']
    for i in range(args.max_iterations):
        fieldnames.extend([f'iter_{i}_line', f'iter_{i}_branch'])
    fieldnames.extend(['final_line', 'final_branch', 'final_iter'])

    # Write results to CSV
    with open(args.output, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    # Calculate and print summary statistics (only classes with final_line > 0)
    valid_results = [r for r in results if r['final_line'] is not None and r['final_line'] > 0]

    print(f"\n=== Statistics ===")
    print(f"Result directory: {args.result_dir}")
    print(f"Total classes analyzed: {len(results)}")
    print(f"Classes with valid final coverage: {len(valid_results)}")

    if valid_results:
        avg_complexity = sum(r['complexity'] for r in valid_results) / len(valid_results)
        print(f"\nAverage Cyclomatic Complexity: {avg_complexity:.2f}")

        # Calculate statistics for each iteration (fill missing with final value)
        print(f"\nLine Coverage:")
        for i in range(args.max_iterations):
            lines = []
            for r in valid_results:
                val = r.get(f'iter_{i}_line')
                if val is None or (isinstance(val, float) and val == 0 and r.get(f'final_line', 0) > 0):
                    # If iter value is missing or zero but final > 0, use final value
                    val = r.get('final_line')
                if val is not None:
                    lines.append(val)
            if lines:
                print(f"  g_{i}: {sum(lines)/len(lines):.2f}% ({len(lines)} samples)")

        final_lines = [r['final_line'] for r in valid_results if r['final_line'] is not None]
        print(f"  Final: {sum(final_lines)/len(final_lines):.2f}%")

        print(f"\nBranch Coverage:")
        for i in range(args.max_iterations):
            branches = []
            for r in valid_results:
                val = r.get(f'iter_{i}_branch')
                if val is None or (isinstance(val, float) and val == 0 and r.get('final_branch', 0) > 0):
                    val = r.get('final_branch')
                if val is not None:
                    branches.append(val)
            if branches:
                print(f"  g_{i}: {sum(branches)/len(branches):.2f}% ({len(branches)} samples)")

        final_branches = [r['final_branch'] for r in valid_results if r['final_branch'] is not None]
        print(f"  Final: {sum(final_branches)/len(final_branches):.2f}%")

    print(f"\nResults saved to: {args.output}")


if __name__ == '__main__':
    main()
