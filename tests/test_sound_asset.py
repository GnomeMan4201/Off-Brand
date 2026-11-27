"""Guard against accidentally replacing the approved audio sample."""
import hashlib
from pathlib import Path
import wave


def test_broadcast_snow_is_exact_approved_sample():
    path = Path(__file__).resolve().parent.parent / "site/sounds/broadcast-snow.wav"
    assert path.is_file(), "Attach the original approved Broadcast Snow WAV before merging."
    assert hashlib.sha256(path.read_bytes()).hexdigest() == "624e6dd9708ca1d1ac9d6246e333c0894135a5183a46b7e6daece36e9155e9f7"
    with wave.open(str(path)) as f:
        assert (f.getnchannels(), f.getsampwidth(), f.getframerate(), f.getnframes()) == (1, 2, 44100, 25578)
