from nekofetch.core.security import TokenCipher


def test_roundtrip():
    cipher = TokenCipher("a-test-secret")
    token = "123456:ABC-DEF_bot_token"
    assert cipher.decrypt(cipher.encrypt(token)) == token


def test_ciphertext_differs_from_plaintext():
    cipher = TokenCipher("another-secret")
    assert cipher.encrypt("hello") != "hello"


def test_any_secret_string_is_accepted():
    # Keys of arbitrary length are derived to a valid Fernet key.
    for secret in ("x", "a" * 5, "a" * 100):
        c = TokenCipher(secret)
        assert c.decrypt(c.encrypt("v")) == "v"
