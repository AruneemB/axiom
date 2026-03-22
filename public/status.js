(async function () {
  const el = document.getElementById('status');
  const text = document.getElementById('status-text');
  const stats = document.getElementById('stats');
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    if (d.status === 'active') {
      el.className = 'status active';
      text.textContent = 'Active';
      document.getElementById('papers').textContent = d.total_papers.toLocaleString();
      document.getElementById('ideas').textContent = d.total_ideas.toLocaleString();
      stats.classList.add('visible');
    } else {
      throw new Error();
    }
  } catch {
    el.className = 'status error';
    text.textContent = 'Unreachable';
  }
})();
