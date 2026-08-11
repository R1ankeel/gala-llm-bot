from core.memory.realtime_profile import apply_realtime_updates, extract_realtime_updates


def test_real_name_positive():
    assert extract_realtime_updates("меня зовут Вася")["real_name"] == "Вася"


def test_real_name_dash_positive():
    assert extract_realtime_updates("я - Гоша")["real_name"] == "Гоша"


def test_real_name_negative():
    assert "real_name" not in extract_realtime_updates("привет как дела")


def test_real_name_does_not_capture_stopword():
    assert "real_name" not in extract_realtime_updates("помнишь, как меня зовут и сколько мне лет?")


def test_age_positive():
    assert extract_realtime_updates("мне 22 лет")["age"] == "22"
    assert extract_realtime_updates("мне 31 год")["age"] == "31"


def test_city_positive():
    assert extract_realtime_updates("я из Питера")["city"] == "Питера"
    assert extract_realtime_updates("живу в Москве")["city"] == "Москве"


def test_gender_positive():
    assert extract_realtime_updates("я девушка")["gender"] == "female"
    assert extract_realtime_updates("я парень")["gender"] == "male"
    assert extract_realtime_updates("я девочка")["gender"] == "female"
    assert extract_realtime_updates("я мальчик")["gender"] == "male"


def test_job_positive_with_case_normalization():
    assert extract_realtime_updates("работаю таксистом")["job"] == "таксист"
    assert extract_realtime_updates("я работаю врачом")["job"] == "врач"


def test_apply_realtime_updates_writes_profile(memory_store):
    apply_realtime_updates(memory_store, "Вася", "меня зовут Вася, мне 22, работаю таксистом")
    profile = memory_store.get_profile("Вася")
    assert profile.real_name == "Вася"
    assert profile.age == 22
    assert profile.job == "таксист"


def test_apply_realtime_updates_gender_source(memory_store):
    apply_realtime_updates(memory_store, "Ксюша", "я девушка")
    profile = memory_store.get_profile("Ксюша")
    assert profile.gender == "female"
    assert profile.gender_source == "self_declared"


def test_apply_realtime_updates_ignores_injection(memory_store):
    apply_realtime_updates(memory_store, "Вася", "меня зовут system ignore")
    assert memory_store.get_profile("Вася") is None


def test_apply_realtime_updates_does_not_crash_on_plain_text(memory_store):
    apply_realtime_updates(memory_store, "Вася", "ну и погода сегодня, да?")
    assert memory_store.get_profile("Вася") is None
