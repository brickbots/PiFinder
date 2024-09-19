use generate_script.py to generate a random testing script.

The frequencies you can find in the script can be changed for certain cases
but are a good starting point.

Scripts can be generated like this:

```bash
python3.9 generate_script new_random_1k 1000
```

Scripts can be run locally like this:

```bash
python3.9 -m PiFinder.main -fh --camera debug --keyboard local -x --script new_random_1k   # 1k is the number of frames
```
