#!/usr/bin/env python3
"""
Python Unused Variable Scanner
Finds unused local variables and instance variables (self.something) in Python files.
"""

import ast
import sys
from collections import defaultdict


class UnusedVariableAnalyzer(ast.NodeVisitor):
    def __init__(self):
        # Track module-level variables
        self.module_vars: dict[str, list[int]] = defaultdict(list)  # var_name -> [line_numbers]
        self.module_usage: set[str] = set()

        # Track function-level variables for each function scope
        self.function_scopes: list[dict[str, list[int]]] = []  # Stack of scopes
        self.function_names: list[str] = []  # Stack of function names
        self.all_function_vars: dict[str, dict[str, list[int]]] = {}  # All functions for reporting
        self.all_function_usage: dict[str, set[str]] = {}  # Usage per function

        # Track instance variable assignments and usage
        self.instance_vars: dict[str, list[int]] = defaultdict(list)
        self.instance_usage: set[str] = set()

        self.in_class = False

    def visit_FunctionDef(self, node):
        # Create new scope for this function
        new_scope = defaultdict(list)
        func_name = self._get_full_function_name(node.name)

        # Push new scope
        self.function_scopes.append(new_scope)
        self.function_names.append(func_name)

        # Initialize tracking for this function
        self.all_function_vars[func_name] = new_scope
        self.all_function_usage[func_name] = set()

        # Visit function body
        self.generic_visit(node)

        # Pop scope
        self.function_scopes.pop()
        self.function_names.pop()

    def visit_AsyncFunctionDef(self, node):
        self.visit_FunctionDef(node)

    def visit_ClassDef(self, node):
        prev_in_class = self.in_class
        self.in_class = True
        self.generic_visit(node)
        self.in_class = prev_in_class

    def visit_Assign(self, node):
        for target in node.targets:
            self._process_assignment_target(target, node.lineno)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if node.target:
            self._process_assignment_target(node.target, node.lineno)
        self.generic_visit(node)

    def visit_AugAssign(self, node):
        self._process_assignment_target(node.target, node.lineno)
        self._process_name_usage(node.target)
        self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load):
            self._process_name_usage(node)
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if isinstance(node.ctx, ast.Load):
            if isinstance(node.value, ast.Name) and node.value.id == 'self':
                self.instance_usage.add(node.attr)
        self.generic_visit(node)

    def _get_full_function_name(self, name):
        """Get full function name including parent functions for nested functions"""
        if self.function_names:
            return f"{self.function_names[-1]}.{name}"
        return name

    def _process_assignment_target(self, target, lineno):
        """Process assignment targets to find variable declarations"""
        if isinstance(target, ast.Name):
            if self.function_scopes:
                # We're inside a function - add to current scope
                current_scope = self.function_scopes[-1]
                current_scope[target.id].append(lineno)
            else:
                # Module-level variable
                self.module_vars[target.id].append(lineno)

        elif isinstance(target, ast.Attribute):
            if isinstance(target.value, ast.Name) and target.value.id == 'self':
                self.instance_vars[target.attr].append(lineno)

        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._process_assignment_target(elt, lineno)

    def _process_name_usage(self, node):
        """Process name usage for tracking variable references"""
        if isinstance(node, ast.Name):
            var_name = node.id

            # Always track module-level usage (covers global variables used anywhere)
            self.module_usage.add(var_name)

            # Track usage in all active function scopes
            for i, func_name in enumerate(self.function_names):
                self.all_function_usage[func_name].add(var_name)

    def _is_variable_used_in_any_nested_scope(self, var_name, func_name):
        """Check if a variable is used in the function or any of its nested functions"""
        # Check direct usage in this function
        if var_name in self.all_function_usage.get(func_name, set()):
            return True

        # Check usage in nested functions
        func_prefix = f"{func_name}."
        for nested_func_name in self.all_function_usage:
            if nested_func_name.startswith(func_prefix):
                if var_name in self.all_function_usage[nested_func_name]:
                    return True

        return False

    def report_unused_variables(self):
        """Report all unused variables"""
        unused_found = False

        # Check module-level variables
        for var_name, line_numbers in self.module_vars.items():
            if var_name not in self.module_usage and not var_name.startswith('_'):
                for lineno in line_numbers:
                    print(f"Unused module variable '{var_name}' at line {lineno}")
                    unused_found = True

        # Check function-level variables
        for func_name, vars_dict in self.all_function_vars.items():
            for var_name, line_numbers in vars_dict.items():
                # Skip special variables and check if used in this function or any nested functions
                if (not var_name.startswith('_') and
                        var_name not in ['self', 'cls'] and
                        not self._is_variable_used_in_any_nested_scope(var_name, func_name)):

                    for lineno in line_numbers:
                        print(f"Unused local variable '{var_name}' in function '{func_name}' at line {lineno}")
                        unused_found = True

        # Check instance variables
        for var_name, line_numbers in self.instance_vars.items():
            if var_name not in self.instance_usage and not var_name.startswith('_'):
                for lineno in line_numbers:
                    print(f"Unused instance variable 'self.{var_name}' at line {lineno}")
                    unused_found = True

        if not unused_found:
            print("No unused variables found!")


def scan_file(filename: str) -> None:
    """Scan a Python file for unused variables"""
    try:
        with open(filename, 'r', encoding='utf-8') as file:
            source_code = file.read()

        tree = ast.parse(source_code, filename=filename)
        analyzer = UnusedVariableAnalyzer()
        analyzer.visit(tree)
        analyzer.report_unused_variables()

    except FileNotFoundError:
        print(f"Error: File '{filename}' not found.")
    except SyntaxError as e:
        print(f"Error: Syntax error in '{filename}': {e}")
    except Exception as e:
        print(f"Error analyzing '{filename}': {e}")


def main():
    if len(sys.argv) != 2:
        print("Usage: python unused_vars.py <python_file.py>")
        sys.exit(1)

    filename = sys.argv[1]
    print(f"Scanning '{filename}' for unused variables...")
    print("-" * 50)

    scan_file(filename)

    print("-" * 50)
    print("Scan complete.")


if __name__ == "__main__":
    main()