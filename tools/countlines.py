#!/usr/bin/env python3
"""
Count the number of code lines (non-empty, non-comment) in each Python file in the parent folder (excludes tools files)
"""

from pathlib import Path

def count_code_lines_in_file(filepath: Path) -> int:
    """
    Counts lines in a file ignoring blank lines and lines starting with '#'.
    """
    count = 0
    try:
        with filepath.open('r', encoding='utf-8') as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith('#'):
                    count += 1
    except (OSError, UnicodeDecodeError) as e:
        print(f"Warning: Could not read {filepath}: {e}")
    return count

def main():
    current_dir = Path.cwd().parent
    py_files = list(current_dir.glob('*.py'))

    total_files = len(py_files)
    total_code_lines = 0

    for py_file in py_files:
        code_lines = count_code_lines_in_file(py_file)
        total_code_lines += code_lines
        print(f"File {py_file.name} has {code_lines} code lines")

    print('-' * 80)
    print("Analysis of project's number of code lines:")
    print(f'> Number of Python files: {total_files}')
    print(f'> Total lines of code in files: {total_code_lines}')

if __name__ == "__main__":
    main()
