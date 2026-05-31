"""Advanced Slavic morph + idiom regression tests."""
import glossary_inflection as gi
import slavic_advanced_morph as sam
import slavic_idioms as si
import translation_quality as tq

tests_morph = [
    ("Я читает книгу.", "читаю", "ru"),
    ("Они работает.", "работают", "ru"),
    ("Я говорю друг письмо.", "другу", "ru"),
    ("Я говорю друг письмо.", "письмо", "ru"),
    ("книга, который я читаю", "которая", "ru"),
    ("Он влияет на политика.", "политику", "ru"),
]

tests_idiom = [
    ("Он принимает место завтра.", "происходит", "ru"),
    ("Он делает фото.", "фотографирует", "ru"),
    ("Он принимает участие на конференции.", "в", "ru"),
]

print("=== advanced morph ===")
fail = 0
for s, k, lang in tests_morph:
    r = sam.fix_sentence_advanced_slavic_morphology(s, lang)
    ok = k.lower() in r.lower()
    if not ok:
        fail += 1
    print("OK" if ok else "??", s, "=>", r)

print("=== idioms ===")
for s, k, lang in tests_idiom:
    r = si.apply_target_collocation_fixes(s, lang)
    ok = k.lower() in r.lower()
    if not ok:
        fail += 1
    print("OK" if ok else "??", s, "=>", r)

print("=== full chain ===")
s = "Я читает книгу и принимает место."
r = tq.postprocess_translation_target(s, "ru")
print(s, "=>", r)
print("failures:", fail)
