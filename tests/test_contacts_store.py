from voice_neves.contacts_store import ContactsStore


def test_contacts_save_and_load(tmp_path):
    path = tmp_path / "contacts.json"
    store = ContactsStore(path=str(path))
    assert store.load() == []

    contacts = [
        {"name": "João", "number": "3000", "server": "pbx", "favorite": True,
         "ringtone": "", "monitor_presence": False},
        {"name": "Ana", "number": "4000", "server": "", "favorite": False,
         "ringtone": "/x.wav", "monitor_presence": True},
    ]
    store.save(contacts)

    loaded = store.load()
    assert len(loaded) == 2
    assert loaded[0]["name"] == "João"
    assert loaded[0]["favorite"] is True
    assert loaded[1]["monitor_presence"] is True


def test_contacts_load_missing(tmp_path):
    store = ContactsStore(path=str(tmp_path / "nope.json"))
    assert store.load() == []


def test_contacts_load_filters_malformed(tmp_path):
    path = tmp_path / "c.json"
    path.write_text('[{"name": "ok", "number": "1"}, {"name": "sem-numero"}]', encoding="utf-8")
    store = ContactsStore(path=str(path))
    loaded = store.load()
    assert len(loaded) == 1
    assert loaded[0]["number"] == "1"
