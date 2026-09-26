from pathlib import Path

def parse_meta(path) -> dict[str, str]:
    result = {}
    with open(path, "r") as meta_file:
        for line in meta_file.readlines():
            cleaned_line = line.strip()
            if cleaned_line[-1] == ";":
                cleaned_line = cleaned_line[:-1]

            kv_pair = [component.strip() for component in cleaned_line.split("=")]

            if len(kv_pair) != 2:
                print(f"Meta.cpp parser error - couldn't interpret: {line}")
                continue

            key = kv_pair[0]
            value = kv_pair[1]

            if value[0] == "\"" and value[-1] == "\"":
                value = value[1:-1]

            result[key] = value

    return result

def lowercase_all_files_at_path(path: Path):
    for original_path in path.rglob("*"):
        original_path.rename(original_path.with_name(original_path.name.lower()))
