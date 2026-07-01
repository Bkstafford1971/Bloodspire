#!/usr/bin/env python3

line = "7 MINUTE ABS                     6   0   0   31  COME OUT AND PLAY (48)"
parts = line.split()

print(f"Line: {line}")
print(f"Parts ({len(parts)}): {parts}")
print("\nPart analysis:")
for i, part in enumerate(parts):
    try:
        val = int(part)
        print(f"  [{i}] {part:20} <- NUMBER {val}")
    except ValueError:
        print(f"  [{i}] {part:20}")
