import js from "@eslint/js";
import pluginVue from "eslint-plugin-vue";
import pluginJsdoc from "eslint-plugin-jsdoc";
import globals from "globals";

/**
 * Flat ESLint config for the CamBrain dashboard.
 *
 * `jsdoc/require-jsdoc` is load-bearing, not stylistic: with no TypeScript,
 * JSDoc is the only machine-checked contract on module boundaries
 * (spec.md §9.2). It must fail loudly when absent.
 *
 * Prettier owns whitespace. `vue/singleline-html-element-content-newline`
 * fights prettier's own HTML formatting — prettier keeps a short element
 * inline while the rule demands line breaks — so the rule is disabled
 * rather than letting two formatters disagree on every `.vue` file.
 */
export default [
  { ignores: ["dist/**", "node_modules/**"] },
  js.configs.recommended,
  ...pluginVue.configs["flat/recommended"],
  pluginJsdoc.configs["flat/recommended"],
  {
    files: ["**/*.js"],
    languageOptions: {
      sourceType: "module",
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      "jsdoc/require-jsdoc": [
        "error",
        {
          require: {
            FunctionDeclaration: true,
            FunctionExpression: false,
            ArrowFunctionExpression: true,
            ClassDeclaration: false,
            ClassExpression: false,
            MethodDefinition: false,
          },
          publicOnly: true,
        },
      ],
    },
  },
  {
    files: ["**/*.vue"],
    rules: {
      "vue/multi-word-component-names": "off",
      "vue/singleline-html-element-content-newline": "off",
    },
  },
];
