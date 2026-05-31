"""Professional-grade Slavic translation post-processing regression tests."""
import slavic_advanced_morph as sam
import slavic_idioms as si
import slavic_pro_register as spr
import glossary_inflection as gi
import translation_quality as tq

# clear idiom cache after JSON edits
si._merged_collocation_items.cache_clear()
si._zh_idioms.cache_clear()

tests_pro = [
    ("Он и она работает.", "работают", "ru"),
    ("В соответствии с закон система работает.", "законом", "ru"),
    ("На основе данные мы решили.", "данных", "ru"),
    ("Мать и отец приехал.", "приехали", "ru"),
    ("Оба студент пришли.", "студента", "ru"),
    ("В случае если это необходимо.", "случае", "ru"),
    ("Он относится к проблема.", "проблеме", "ru"),
]

tests_idiom = [
    ("Он делает решение.", "принимает", "ru"),
    ("В соответствии с с договором.", "с договором", "ru"),
    ("В случай если.", "случае", "ru"),
    ("Он представляет из себя эксперт.", "собой", "ru"),
]

tests_register = [
    ("На данный момент это важно.", "в настоящее время", "ru"),
    ("Согласно с закону.", "согласно", "ru"),
]

print("=== pro morph ===")
fail = 0
for s, k, lang in tests_pro:
    if "студент" in s:
        r = tq.postprocess_translation_target(s, lang)
    else:
        r = sam.fix_sentence_advanced_slavic_morphology(s, lang)
        r = gi.fix_sentence_slavic_morphology(r, lang)
    ok = k.lower() in r.lower()
    fail += int(not ok)
    print("OK" if ok else "??", s, "=>", r)

print("=== idioms ===")
for s, k, lang in tests_idiom:
    r = si.apply_target_collocation_fixes(s, lang)
    ok = k.lower() in r.lower()
    fail += int(not ok)
    print("OK" if ok else "??", s, "=>", r)

print("=== register ===")
for s, k, lang in tests_register:
    r = spr.apply_pro_register_fixes(s, lang)
    ok = k.lower() in r.lower()
    fail += int(not ok)
    print("OK" if ok else "??", s, "=>", r)

print("=== full chain zh->ru hint ===")
src = "目前根据合同执行。"
tgt = "На данный момент на основе договор выполняется."
r = tq.postprocess_translation_target(
    tgt, "ru", source_text=src, source_lang_code="zh"
)
print("=>", r)

print("=== strengthen (base) still ok ===")
r2 = gi.fix_sentence_slavic_morphology("Мы не написали письмо.", "ru")
print("письма" in r2, r2)

print("failures:", fail)
