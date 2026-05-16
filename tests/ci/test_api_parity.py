from havocforge.api import build_generator, generate_many, Havocforge


def test_functional_vs_oop_parity():
    spec = {
        "type": "array",
        "min_items": 2,
        "max_items": 2,
        "child": {
            "type": "object",
            "fields": {
                "id": {"type": "int", "min_value": 1, "max_value": 10},
                "name": {"type": "string", "string_type": "name"},
                "active": {"type": "bool"},
            },
        },
    }
    gen = build_generator(spec)
    func_rows = generate_many(gen, n=3, seed=123, locale="en_US")

    engine = Havocforge(seed=123, locale="en_US")
    gen2 = engine.build(spec)
    oop_rows = engine.generate_many(gen2, n=3)

    assert func_rows == oop_rows
