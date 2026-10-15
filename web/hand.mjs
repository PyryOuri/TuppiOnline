// Geometry only: card IDs, legality and rank order belong to the session/table.
export function handGeometry({count, width, compact = false, expanded = false, scale = 1}) {
  const available = Math.max(1, width), size = Math.max(1, scale);
  const cardWidth = (compact || expanded ? 64 : 60) * size;
  const cardHeight = cardWidth * 1.42;
  const gap = 8 * size;
  const capacity = expanded ? Math.max(1, Math.floor((available + gap) / (cardWidth + gap))) :
    compact ? Math.max(1, Math.min(7, Math.floor((available - cardWidth) / (40 * size)) + 1)) : Math.max(1, count);
  const columns = Math.min(Math.max(1, count), capacity);
  const stride = expanded ? cardWidth + gap : compact ? Math.min(48 * size, (available - cardWidth) / Math.max(1, columns - 1)) :
    count > 1 ? Math.min(40, Math.max(30, Math.floor((available - cardWidth) / (count - 1)))) : 0;
  const step = Math.max(0, stride), rows = Math.ceil(count / capacity);
  const occupied = cardWidth + Math.max(0, columns - 1) * step;
  return {cardWidth, cardHeight, capacity, rows, width: Math.max(cardWidth, occupied),
    height: rows ? rows * cardHeight + (rows - 1) * gap : 0,
    positions: Array.from({length: count}, (_, index) => ({
      x: index % capacity * step, y: Math.floor(index / capacity) * (cardHeight + gap),
    }))};
}

// Keep card nodes through selection, checkpoints and connection updates. This
// preserves keyboard/assistive focus; only a changed hand changes DOM order.
export class HandView {
  constructor(element, create, update) {
    this.element = element; this.create = create; this.update = update; this.cards = new Map();
  }
  render(ids, state) {
    const nodes = ids.map(id => {
      if (!this.cards.has(id)) this.cards.set(id, this.create(id));
      const node = this.cards.get(id); this.update(node, id, state); return node;
    });
    for (const id of this.cards.keys()) if (!ids.includes(id)) this.cards.delete(id);
    if (nodes.length !== this.element.children.length || nodes.some((node, i) => node !== this.element.children[i])) {
      this.element.replaceChildren(...nodes);
    }
  }
  layout(options) {
    const geometry = handGeometry({count: this.element.children.length, ...options});
    this.element.style.width = `${geometry.width}px`;
    this.element.style.height = `${geometry.height}px`;
    this.element.style.setProperty('--hand-card-width', `${geometry.cardWidth}px`);
    this.element.style.setProperty('--hand-card-height', `${geometry.cardHeight}px`);
    geometry.positions.forEach(({x, y}, i) => {
      this.element.children[i].style.setProperty('--card-x', `${x}px`);
      this.element.children[i].style.setProperty('--card-y', `${y}px`);
    });
    return geometry;
  }
}
