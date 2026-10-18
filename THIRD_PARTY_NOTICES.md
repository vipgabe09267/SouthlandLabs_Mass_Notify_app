# Speech components and voice attribution

The desktop app uses [Piper 1.8.0](https://github.com/OHF-Voice/piper1-gpl/tree/639388b6317fc4731e91d53da42aea68fd4166ff), distributed under GPL-3.0-or-later, including its eSpeak NG phonemizer. Corresponding Piper source and build instructions are available at that pinned source revision and in the [1.8.0 source distribution](https://pypi.org/project/piper-tts/1.8.0/#files). The installed `_internal` directory includes dependency license notices and Piper's full license text. ONNX Runtime, NumPy, protobuf, flatbuffers and pathvalidate retain their upstream licenses.

Voice models are unmodified files from [rhasspy/piper-voices, revision c10ece1aade47bb51c153c893d14e5bf8e5b7117](https://huggingface.co/rhasspy/piper-voices/tree/c10ece1aade47bb51c153c893d14e5bf8e5b7117). The catalog records their exact URLs, sizes and SHA-256 hashes. Only Lessac low and its upstream `MODEL_CARD` are bundled under `_internal/tts`. Optional voices and their model cards are downloaded on request into the Windows user's local application data. The application's license does not replace individual voice and dataset terms.

| Voice | Upstream model card: dataset attribution and terms |
| --- | --- |
| English (US), Lessac low and medium | [Lessac / Blizzard 2013](https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/), with [research license terms](https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/license.html). |
| English (US), Amy low | [Mycroft Mimic 3 voices](https://github.com/MycroftAI/mimic3-voices); model card refers to upstream licensing and records fine-tuning from Ryan low. |
| English (US), Ryan low | [RyanSpeech dataset](https://www.kaggle.com/datasets/roholazandie/ryanspeech), [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). Noncommercial restriction applies to the licensed material. |
| French, Siwis medium | [SIWIS French Speech Synthesis Database](https://datashare.is.ed.ac.uk/handle/10283/2353), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); fine-tuned from Lessac medium. |
| German, Thorsten low | [Thorsten Müller / Thorsten-Voice](https://github.com/thorstenMueller/Thorsten-Voice), CC0 dataset; fine-tuned from Ryan low. |
| Portuguese (Brazil), Faber medium | [OHF Voice datasets](https://github.com/OHF-Voice/voice-datasets), CC0 dataset; fine-tuned from Lessac medium. |
| Spanish, Davefx medium | [OHF Voice datasets](https://github.com/OHF-Voice/voice-datasets), CC0 dataset; fine-tuned from Lessac medium. |

Voice selection changes pronunciation, not the language of a message. These notices do not grant additional voice rights. Public redistribution or commercial deployment needs to respect the upstream terms, including training provenance; the voice bundle has not been cleared for unrestricted commercial use.
