Звуковой движок партитурного проигрывателя (2026-11-08).
spessasynth_lib 4.4.7 и spessasynth_core 4.4.9 (Apache-2.0, https://github.com/spessasus/spessasynth_lib), лицензия рядом.
spessa_lib.min.js собран из npm-пакета так:  echo 'import {WorkletSynthesizer, Sequencer} from "spessasynth_lib";
window.Spessa = {WorkletSynthesizer, Sequencer};' > entry.js && npx esbuild@0.24.2 entry.js --bundle --format=iife --minify
spessasynth_processor.min.js скопирован из dist/ пакета без изменений.
