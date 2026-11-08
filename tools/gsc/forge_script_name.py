"""Makes a script function name that hashes to a given value.

Workshop scripts only keep name hashes. To supply a function a map links to, give it a name with the same hash:
    python forge_script_name.py ef7f0034 mzo_map_mule_cb_
Prints the prefix plus 8 characters. Guide: _handoff/custom-map-fixes.md
"""
import itertools
import string
import sys

PRIME = 0x1000193
PRIME_INVERSE = pow(PRIME, -1, 1 << 32)
MASK = 0xFFFFFFFF
ALPHABET = (string.ascii_lowercase + string.digits).encode()
HALF = 4


def script_hash(text):
    value = 0x4B9ACE2F
    for byte in text.encode():
        value = ((value ^ byte) * PRIME) & MASK
    return (value * PRIME) & MASK


def forge(target, prefix):
    """Meets in the middle, since each FNV step can be undone."""
    start = 0x4B9ACE2F
    for byte in prefix.encode():
        start = ((start ^ byte) * PRIME) & MASK
    forward = {}
    for chars in itertools.product(ALPHABET, repeat=HALF):
        value = start
        for byte in chars:
            value = ((value ^ byte) * PRIME) & MASK
        forward.setdefault(value, bytes(chars))
    goal = (target * PRIME_INVERSE) & MASK  # undo the final extra multiply
    for chars in itertools.product(ALPHABET, repeat=HALF):
        value = goal
        for byte in reversed(chars):
            value = ((value * PRIME_INVERSE) & MASK) ^ byte
        if value in forward:
            return prefix + forward[value].decode() + bytes(chars).decode()
    return None


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    target = int(sys.argv[1], 16)
    prefix = sys.argv[2].lower()
    name = forge(target, prefix)
    if name is None or script_hash(name) != target:
        sys.exit('no name found, try another prefix')
    print(name)


if __name__ == '__main__':
    main()
