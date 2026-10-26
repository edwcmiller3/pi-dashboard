// document is touched only inside el(), never at module scope (the core graph is
// side-effect-free on import, see core/machine.js).

/**
 * @param {string} tag
 * @param {string | null} [className]
 * @param {string} [text]
 * @returns {HTMLElement}
 */
export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}
