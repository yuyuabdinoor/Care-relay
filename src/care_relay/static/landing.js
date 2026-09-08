const chapters = [...document.querySelectorAll(".chapter")];
const navButtons = [...document.querySelectorAll(".scene-nav button")];
const sceneNumber = document.querySelector("#scene-number");

function setScene(index) {
  const next = Math.max(0, Math.min(chapters.length - 1, index));
  document.body.dataset.scene = String(next);
  sceneNumber.textContent = String(next + 1).padStart(2, "0");
  chapters.forEach((chapter, i) => chapter.classList.toggle("active", i === next));
  navButtons.forEach((button, i) => {
    button.classList.toggle("active", i === next);
    button.setAttribute("aria-current", i === next ? "step" : "false");
  });
}

const observer = new IntersectionObserver(
  entries => {
    const visible = entries
      .filter(entry => entry.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (visible) setScene(Number(visible.target.dataset.scene));
  },
  { threshold: [0.35, 0.55, 0.75], rootMargin: "-10% 0px -10% 0px" }
);

chapters.forEach(chapter => observer.observe(chapter));
navButtons.forEach(button => button.addEventListener("click", () => {
  chapters[Number(button.dataset.jump)].scrollIntoView({ behavior: "smooth", block: "start" });
}));

function syncSceneToViewport() {
  const viewportCenter = window.innerHeight / 2;
  const nearest = chapters.reduce((best, chapter) => {
    const rect = chapter.getBoundingClientRect();
    const distance = Math.abs(rect.top + rect.height / 2 - viewportCenter);
    return distance < best.distance
      ? { index: Number(chapter.dataset.scene), distance }
      : best;
  }, { index: 0, distance: Number.POSITIVE_INFINITY });
  setScene(nearest.index);
}

const linkedChapter = window.location.hash
  ? document.querySelector(window.location.hash)
  : null;
setScene(linkedChapter?.classList.contains("chapter")
  ? Number(linkedChapter.dataset.scene)
  : 0);
requestAnimationFrame(syncSceneToViewport);
window.addEventListener("hashchange", () => requestAnimationFrame(syncSceneToViewport));
