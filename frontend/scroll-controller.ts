type Maybe<T> = T | null;

function getScrollElements(element: HTMLElement): [Maybe<HTMLUListElement>, Maybe<HTMLButtonElement>, Maybe<HTMLButtonElement>] {
  const list = element.querySelector<HTMLUListElement>('._cls-erh--resourceList');
  const leftArrow = element.querySelector<HTMLButtonElement>('._cls-scroll-control--left');
  const rightArrow = element.querySelector<HTMLButtonElement>('._cls-scroll-control--right');
  return [list, leftArrow, rightArrow];
}

function getListItemAverageWidth(listElement: Maybe<HTMLElement>) {
  const listItems = Array.from(listElement?.querySelectorAll('li') ?? []);
  const averageWidth = listItems.reduce((prev, cur) => prev + cur.clientWidth, 0) / listItems.length;
  return averageWidth;
}

function getScrollPositions(element: Maybe<HTMLElement>) {
  if (!element) return [];
  let width = element.scrollWidth;
  let startPos = element.scrollLeft;
  let endPos = element.clientWidth + startPos;
  return [width, startPos, endPos]
}

function updateArrowState(elements: [Maybe<HTMLButtonElement>, Maybe<HTMLButtonElement>], isStart: boolean, isEnd: boolean) {
  // get arrows
  if (elements[0]) elements[0].disabled = isStart;
  if (elements[1]) elements[1].disabled = isEnd;
}

function updateState(sectionElement: HTMLElement) {
  const [list, leftButton, rightButton] = getScrollElements(sectionElement);
  const [width, startPos, endPos] = getScrollPositions(list);
  updateArrowState([leftButton, rightButton], startPos === 0, endPos === width);
}

function scrollList(listElement: Maybe<HTMLElement>, direction: 'left' | 'right', amount: number) {
  if (!listElement) return;
  const [width] = getScrollPositions(listElement);
  if (direction === 'left') {
    // when scrolling left, we need to subtract the amount from the scrollLeft value, with a minimum of 0
    listElement.scrollLeft = Math.max(listElement.scrollLeft - amount, 0)
  } else {
    // when scrolling right, we need to add the amount to the scrollLeft value, with a maximum of the width
    listElement.scrollLeft = Math.min(listElement.scrollLeft + amount, width)
  }
}

export function scrollControl() {
  const catalogSections = document.querySelectorAll<HTMLElement>('section._cls-erh--category')
  catalogSections.forEach(catalogSection => {
    const [list, leftButton, rightButton] = getScrollElements(catalogSection);
    const averageWidth = getListItemAverageWidth(list);
    updateState(catalogSection);
    list?.addEventListener('scroll', () => updateState(catalogSection));
    leftButton?.addEventListener('click', () => scrollList(list, 'left', averageWidth));
    rightButton?.addEventListener('click', () => scrollList(list, 'right', averageWidth));
  });
}