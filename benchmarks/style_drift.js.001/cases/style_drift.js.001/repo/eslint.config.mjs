export default [
  {
    files: ["**/*.js"],
    rules: {
      "id-match": ["error", "^[a-z_$][a-z0-9_]*$", { onlyDeclarations: true }],
      "indent": ["error", "tab"],
      "semi": ["error", "never"],
      "quotes": ["error", "single"],
      "max-len": ["warn", { code: 60 }],
    },
  },
];
