// Remote database first; bundled database.json is used if this URL is unavailable.
window.AITS_CONFIG = {
  // Set maintenanceMode to true to show the maintenance page to visitors.
  // Set to false when maintenance is complete to restore regular portal access.
 
  databaseUrl: 'https://huggingface.co/datasets/anwehsh/aits-physics/resolve/main/database.json',
  chemistryUrl: 'https://huggingface.co/datasets/anwehsh/aits-physics/resolve/main/chemistry_database.json',
  mathsAdvancedUrl: 'https://huggingface.co/datasets/anwehsh/aits-physics/resolve/main/maths_advanced_database.json',
  mathsMainUrl: 'https://huggingface.co/datasets/anwehsh/aits-physics/resolve/main/maths_main_database.json'
};
