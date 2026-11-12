// Bundled database first for instant loading and zero CORS issues; Hugging Face is used as fallback.
window.AITS_CONFIG = {
  databaseUrl: 'https://huggingface.co/datasets/anwehsh/aits-physics/resolve/main/database.json',
  chemistryUrl: 'https://huggingface.co/datasets/anwehsh/aits-physics/resolve/main/chemistry_database.json?v=4',
  mathsAdvancedUrl: 'https://huggingface.co/datasets/anwehsh/aits-physics/resolve/main/maths_advanced_database.json',
  mathsMainUrl: 'https://huggingface.co/datasets/anwehsh/aits-physics/resolve/main/maths_main_database.json',
  allenChemUrl: 'allenchem_database.json',
  reportWebhookUrl: 'https://script.google.com/macros/s/AKfycbz22mMoGU674mjLTxD-ttP0vJnppoq9qVOZDHqWEBPT9pJgMJVDo5sbttujc0QRP1w/exec',
  localVectorEngineUrl: 'http://localhost:8000', // Fast local engine (1-2s instant generation)
  vectorEngineUrl: '' // Disabled Render.com cloud engine - generate pure client-side PDF in browser
};
