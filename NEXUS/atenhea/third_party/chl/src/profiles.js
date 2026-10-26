const PROFILE_DEFAULTS = {
  default: {
    bitCount: 128,
    bandBits: 32,
    hyperDim: 256,
    maxEntries: 4096,
    maxCandidates: 64,
  },
  large: {
    bitCount: 128,
    bandBits: 32,
    hyperDim: 256,
    maxEntries: 20000,
    maxCandidates: 96,
  },
};

function resolveMemoryProfile(options = {}) {
  const profile = options.profile ?? process.env.CHL_PROFILE ?? "default";
  const preset = PROFILE_DEFAULTS[profile] ?? PROFILE_DEFAULTS.default;
  const largeProfile = options.largeProfile ?? profile === "large";
  return {
    ...preset,
    ...options,
    profile,
    largeProfile,
  };
}

module.exports = {
  PROFILE_DEFAULTS,
  resolveMemoryProfile,
};
