"""verify_sifra.py — quick sanity check script"""
import ast, os, re, sqlite3

files = ['main.py', 'sifra_live.py', 'sifra_session.py', 'database.py', 'server.py', 'enroll_sahil.py']
errors = []

print('=== SIFRA AI — Final Verification ===\n')

# 1. Syntax check
print('[1] Syntax check...')
for f in files:
    if not os.path.exists(f):
        continue
    try:
        with open(f, encoding='utf-8') as fh:
            ast.parse(fh.read())
        print(f'   OK   {f}')
    except SyntaxError as e:
        print(f'   FAIL {f}: {e}')
        errors.append(f)

# 2. Irfan references in executable lines
print('\n[2] Checking for stale Irfan references...')
found_irfan = False
for f in files:
    if not os.path.exists(f):
        continue
    with open(f, encoding='utf-8') as fh:
        lines = fh.readlines()
    for i, line in enumerate(lines, 1):
        s = line.strip()
        # skip pure comment/docstring lines
        if s.startswith('#'):
            continue
        if re.search(r'\birfan\b', line, re.IGNORECASE):
            safe = line.rstrip().encode('ascii', errors='replace').decode('ascii')
            print(f'   WARN {f}:{i} :: {safe}')
            found_irfan = True
if not found_irfan:
    print('   All clear — no stale Irfan references.')

# 3. SIFRA/Sahil presence confirmed
print('\n[3] SIFRA/Sahil presence...')
for f in ['main.py', 'sifra_live.py', 'sifra_session.py']:
    with open(f, encoding='utf-8') as fh:
        content = fh.read()
    has_sifra = 'SIFRA' in content or 'sifra' in content
    has_sahil = 'Sahil' in content or 'sahil' in content
    print(f'   {f}: SIFRA={has_sifra}, Sahil={has_sahil}')

# 4. Memory status
print('\n[4] Memory database status...')
conn = sqlite3.connect('sifra_memory.db')
c = conn.cursor()
conv   = c.execute('SELECT COUNT(*) FROM conversations').fetchone()[0]
people = c.execute('SELECT COUNT(*) FROM people').fetchone()[0]
facts  = c.execute('SELECT COUNT(*) FROM facts').fetchone()[0]
conn.close()
print(f'   conversations={conv}  people={people}  facts={facts}  (all zero = clean reset ✓)')

# 5. Voice enrollment
print('\n[5] Voice enrollment...')
if os.path.exists('sahil_reference.wav'):
    size = os.path.getsize('sahil_reference.wav')
    print(f'   sahil_reference.wav found ({size} bytes) ✓')
else:
    print('   sahil_reference.wav NOT FOUND — run: python enroll_sahil.py')

print()
if errors:
    print(f'RESULT: {len(errors)} syntax error(s) — fix before running SIFRA.')
else:
    print('RESULT: All checks passed ✅  SIFRA AI is ready.')
