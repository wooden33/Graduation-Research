"""
Calculate per-project statistics from coverage results.
"""
import argparse
import csv
from collections import defaultdict
from statistics import mean, stdev


def load_coverage_data(csv_path):
    """Load coverage data from CSV file."""
    data = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)
    return data


def calculate_project_stats(data):
    """Calculate statistics for each project."""
    projects = defaultdict(list)

    for row in data:
        project = row['project']
        projects[project].append(row)

    results = []

    for project, classes in sorted(projects.items()):
        # Filter valid entries (non-empty final_line)
        valid_classes = [c for c in classes if c.get('final_line', '').strip()]

        if not valid_classes:
            continue

        # Parse coverage values
        final_lines = [float(c['final_line']) for c in valid_classes if c['final_line']]
        final_branches = [float(c['final_branch']) for c in valid_classes if c['final_branch']]
        complexities = [float(c['complexity']) for c in valid_classes if c['complexity']]

        # Calculate statistics
        stats = {
            'project': project,
            'num_classes': len(valid_classes),
            'avg_complexity': mean(complexities) if complexities else 0,
            'avg_final_line': mean(final_lines) if final_lines else 0,
            'avg_final_branch': mean(final_branches) if final_branches else 0,
            'max_line': max(final_lines) if final_lines else 0,
            'min_line': min(final_lines) if final_lines else 0,
            'max_branch': max(final_branches) if final_branches else 0,
            'min_branch': min(final_branches) if final_branches else 0,
        }

        # Calculate std dev if we have enough data points
        if len(final_lines) > 1:
            stats['std_line'] = stdev(final_lines)
        else:
            stats['std_line'] = 0

        if len(final_branches) > 1:
            stats['std_branch'] = stdev(final_branches)
        else:
            stats['std_branch'] = 0

        # Count classes with coverage > 0
        stats['classes_with_coverage'] = sum(1 for c in final_lines if c > 0)

        results.append(stats)

    return results


def main():
    parser = argparse.ArgumentParser(description='Calculate per-project statistics from coverage results.')
    parser.add_argument('--input', type=str, required=True,
                        help='Input CSV file path')
    parser.add_argument('--output', type=str, default=None,
                        help='Output CSV file path (optional)')

    args = parser.parse_args()

    # Load data
    data = load_coverage_data(args.input)
    print(f"Loaded {len(data)} records")

    # Calculate project statistics
    stats = calculate_project_stats(data)

    # Print summary
    print(f"\n=== Per-Project Statistics ===\n")
    print(f"{'Project':<25} {'Classes':>8} {'Avg Line%':>10} {'Avg Branch%':>12} {'Cov>0':>8}")
    print("-" * 70)

    total_classes = 0
    weighted_line = 0
    weighted_branch = 0

    for s in stats:
        print(f"{s['project']:<25} {s['num_classes']:>8} {s['avg_final_line']:>10.2f} {s['avg_final_branch']:>12.2f} {s['classes_with_coverage']:>8}")
        total_classes += s['num_classes']
        weighted_line += s['avg_final_line'] * s['num_classes']
        weighted_branch += s['avg_final_branch'] * s['num_classes']

    print("-" * 70)
    print(f"\nTotal Projects: {len(stats)}")
    print(f"Total Classes: {total_classes}")

    if total_classes > 0:
        print(f"\nOverall Average Line Coverage: {weighted_line/total_classes:.2f}%")
        print(f"Overall Average Branch Coverage: {weighted_branch/total_classes:.2f}%")

    # Save to CSV if requested
    if args.output:
        with open(args.output, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'project', 'num_classes', 'avg_complexity',
                'avg_final_line', 'avg_final_branch',
                'max_line', 'min_line', 'max_branch', 'min_branch',
                'std_line', 'std_branch', 'classes_with_coverage'
            ])
            writer.writeheader()
            writer.writerows(stats)
        print(f"\nResults saved to: {args.output}")


if __name__ == '__main__':
    main()
