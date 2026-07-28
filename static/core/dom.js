// Core DOM builder — the one tiny imperative helper every layout shares.
//
// Layout-agnostic: it only wraps document.createElement with a class + text
// convenience. document is touched only inside el(), never at module scope — the
// core graph's no-import-side-effects invariant (see core/machine.js for why).

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
