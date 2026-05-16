from havocforge.api import build_generator, generate_one


def test_spec_sugar_normalization():
    spec = {
        "type": "object",
        "fields": {"a": "int", "b": "string", "c": {"type": "bool"}},
    }
    gen = build_generator(spec)
    obj = generate_one(gen, seed=1, locale="en_US")
    assert set(obj.keys()) == {"a", "b", "c"}
