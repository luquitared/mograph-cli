const adjectives = [
  "amber", "azure", "brisk", "cobalt", "crimson", "dusky", "ember", "fern",
  "flint", "gilded", "hazel", "indigo", "ivory", "jade", "lilac", "linen",
  "marble", "mauve", "misty", "neon", "obsidian", "ochre", "olive", "onyx",
  "opal", "orchid", "pearl", "plum", "quartz", "rosy", "rust", "saffron",
  "sage", "sepia", "silver", "slate", "smoky", "spruce", "teal", "tinsel",
  "topaz", "umber", "velvet", "violet", "wheat", "wisp", "amethyst", "auburn",
];

const nouns = [
  "alder", "anchor", "beacon", "bramble", "breeze", "cinder", "clover", "comet",
  "coral", "cove", "crane", "crest", "crow", "dawn", "dove", "drift", "echo",
  "ember", "falcon", "fern", "field", "frost", "glade", "harbor", "haven",
  "haze", "heron", "isle", "lark", "lattice", "lilac", "lichen", "loom",
  "lyre", "marsh", "meadow", "moth", "nest", "orbit", "otter", "pebble",
  "petal", "pine", "pulse", "quill", "ravine", "rill", "river", "shoal",
  "spire", "stone", "swan", "tide", "thicket", "thorn", "vale", "vein",
];

export function randomHandle(): string {
  const a = adjectives[Math.floor(Math.random() * adjectives.length)];
  const n = nouns[Math.floor(Math.random() * nouns.length)];
  const num = Math.floor(Math.random() * 9000 + 1000);
  return `anon-${a}-${n}-${num}`;
}
