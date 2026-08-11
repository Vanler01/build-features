import tseslint from 'typescript-eslint';

export default tseslint.config(
  ...tseslint.configs.strict,
  {
    rules: {
      // AI_PROJECTS.md style: no `any` without a comment justifying it.
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/explicit-function-return-type': 'error',
      'max-len': ['error', { code: 100, ignoreUrls: true }],
    },
  },
  { ignores: ['dist/**', 'node_modules/**', 'extension/dist/**'] },
);
