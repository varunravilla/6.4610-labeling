// Public values: safe to commit. The anon key can only call the labeling functions,
// and every write also needs the team passcode.
window.LABELING_CONFIG = {
  supabaseUrl: "PASTE_SUPABASE_PROJECT_URL",   // e.g. https://abcdefgh.supabase.co
  supabaseAnonKey: "PASTE_SUPABASE_ANON_KEY",  // Supabase > Project Settings > API Keys > anon / publishable
};
