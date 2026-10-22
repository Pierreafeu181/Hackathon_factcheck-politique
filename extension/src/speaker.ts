/** Devine qui parle à partir du titre d'une vidéo politique. */
export function guessFromTitle(title: string): string | undefined {
  const name = "[A-ZÀ-Ý][\\p{L}'’-]+(?:\\s+(?:de\\s+|d['’])?[A-ZÀ-Ý][\\p{L}'’-]+){1,2}";
  const patterns = [
    new RegExp(`^(${name})\\s*[:|–—-]`, "u"), // « Michel Barnier : … »
    new RegExp(`[:|–—-]\\s*(${name})\\s*(?:[-–—|,(]|$)`, "u"), // « Face à Face : Manuel Bompard - 22/10 »
    new RegExp(`(${name}),?\\s+invitée?\\b`, "u"), // « …: Manuel Bompard, invité de BFMTV »
  ];
  for (const re of patterns) {
    const m = title.match(re);
    if (m) return m[1].trim();
  }
  return undefined;
}
