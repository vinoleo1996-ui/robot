import os

def _patch_file(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    new_content = content
    # Replace slots=True
    new_content = new_content.replace("@dataclass(slots=True)", "@dataclass")
    new_content = new_content.replace("@dataclass(slots=True, frozen=True)", "@dataclass(frozen=True)")
    new_content = new_content.replace("@dataclass(slots=True, order=True)", "@dataclass(order=True)")

    # Ensure __future__ annotations for `|` syntax in Python 3.9
    if "from __future__ import annotations" not in new_content:
        # Find the first line that is not a docstring or empty comment
        lines = new_content.split('\n')
        insert_idx = 0
        in_docstring = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not in_docstring and (stripped.startswith('"""') or stripped.startswith("'''")):
                if stripped.count('"""') == 1 or stripped.count("'''") == 1:
                    in_docstring = True
                else:
                    insert_idx = i + 1
                    break
            elif in_docstring and (stripped.count('"""') > 0 or stripped.count("'''") > 0):
                in_docstring = False
                insert_idx = i + 1
                break
            elif not in_docstring and not stripped.startswith('#') and stripped:
                insert_idx = i
                break
                
        lines.insert(insert_idx, "from __future__ import annotations")
        new_content = '\n'.join(lines)
    
    # Fix the missing match/case syntax? Hopefully they didn't use Python 3.10 match/case.
    # We will just patch future annotations.
    if new_content != content:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Patched features for Py3.9: {path}")

def main():
    target_dir = "src/robot_life"
    for root, dirs, files in os.walk(target_dir):
        for file in files:
            if file.endswith('.py'):
                _patch_file(os.path.join(root, file))

if __name__ == '__main__':
    main()
