"""Christian-domain (Orthodox/Catholic/Protestant) Slavic post-processing tests."""
import slavic_idioms as si
import slavic_pro_register as spr
import translation_quality as tq

si._merged_collocation_items.cache_clear()
si._merged_zh_idiom_items.cache_clear()

tests_collocation = [
    ("Он делает молитву каждый день.", "молится", "ru"),
    ("слава богу за это.", "Слава Богу", "ru"),
    ("господи помилуй нас.", "Господи, помилуй", "ru"),
    ("христос воскресе!", "Христос воскрес", "ru"),
    ("первый грех человека.", "первородный грех", "ru"),
    ("Мы читаем хорошие новости.", "Евангелие", "ru"),
    ("Вона робить молитву.", "молиться", "uk"),
]

tests_tradition = [
    ("东正教在教堂举行弥撒。", "проводится месса", "Божественная литургия", "ru"),
    ("天主教在教堂举行弥撒。", "проводится божественная литургия", "месса", "ru"),
    ("新教牧师布道。", "наш священник проповедует", "пастор", "ru"),
    ("东正教圣母像。", "икона дева мария", "Богородица", "ru"),
    ("天主教圣母像。", "икона богородица", "Дева Мария", "ru"),
]

tests_zh_hint = [
    ("他每天都做祷告。", "Он делает молитву каждый день.", "молится", "ru"),
    ("信上帝的人。", "Верующие в небесного отца.", "Бог", "ru"),
    ("他的罪很重。", "Его вина очень тяжёлая.", "грех", "ru"),
    ("哈利路亚！", "Аллилуйя!", "аллилуия", "ru"),
    ("她做祷告。", "Вона робить молитву.", "молиться", "uk"),
]

tests_idiom_chain = [
    ("主啊，怜悯我们。", "Господи помилуй нас.", "Господи, помилуй", "ru"),
]

tests_frozen = [
    ("господи помилуй", "Господи, помилуй", "ru"),
    ("христос воскресе", "Христос воскрес", "ru"),
]

print("=== Christian collocations ===")
fail = 0
for s, k, lang in tests_collocation:
    r = si.apply_target_collocation_fixes(s, lang)
    ok = k.lower() in r.lower()
    fail += int(not ok)
    print("OK" if ok else "??", s, "=>", r)

print("=== tradition-aware zh hints ===")
for src, tgt, k, lang in tests_tradition:
    r = si.apply_idiom_fixes(tgt, lang, source_text=src, source_lang="zh")
    ok = k.lower() in r.lower()
    fail += int(not ok)
    print("OK" if ok else "??", src, "=>", r)

print("=== zh Christian hints ===")
for src, tgt, k, lang in tests_zh_hint:
    r = si.apply_idiom_fixes(tgt, lang, source_text=src, source_lang="zh")
    ok = k.lower() in r.lower()
    fail += int(not ok)
    print("OK" if ok else "??", src, "=>", r)

print("=== idiom + collocation chain ===")
for src, tgt, k, lang in tests_idiom_chain:
    r = si.apply_idiom_fixes(tgt, lang, source_text=src, source_lang="zh")
    ok = k.lower() in r.lower()
    fail += int(not ok)
    print("OK" if ok else "??", src, "=>", r)

print("=== frozen liturgical restore ===")
for s, k, lang in tests_frozen:
    r = spr.restore_frozen_professional_phrases(s, lang)
    ok = k.lower() in r.lower()
    fail += int(not ok)
    print("OK" if ok else "??", s, "=>", r)

print("=== full chain ===")
src = "复活节我们唱哈利路亚，说阿们。"
tgt = "На пасхальный праздник мы поём аллилуйя и говорим amen."
r = tq.postprocess_translation_target(
    tgt, "ru", source_text=src, source_lang_code="zh"
)
print("=>", r)
ok = "аллилуия" in r.lower() and "аминь" in r.lower() and "пасх" in r.lower()
fail += int(not ok)
print("OK" if ok else "??", "paschal chain")

print("failures:", fail)
