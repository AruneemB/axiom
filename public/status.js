(async function () {
  const el = document.getElementById('status');
  const text = document.getElementById('status-text');
  const stats = document.getElementById('stats');
  const ticker = document.getElementById('ticker');

  const topics = [
    "alpha generation",
    "alpha signals",
    "arbitrage free modeling",
    "clustering financial data",
    "contrastive learning",
    "controlled differential equation",
    "derivatives pricing",
    "diffusion models",
    "financial time series",
    "fractional brownian motion",
    "game theory finance",
    "generative models time series",
    "hidden markov models",
    "implied volatility",
    "information geometry",
    "latent variable models",
    "limit order book",
    "local volatility",
    "manifold learning",
    "market microstructure",
    "neural cde",
    "neural sde",
    "optimal execution",
    "optimal transport finance",
    "options pricing",
    "quantitative finance theory",
    "regime detection",
    "reinforcement learning trading",
    "representation learning",
    "rough volatility",
    "score based models",
    "self supervised learning",
    "sequence modeling",
    "state space models",
    "statistical arbitrage",
    "stochastic control",
    "stochastic differential equation",
    "stochastic volatility",
    "term structure modeling",
    "time series representation learning",
    "transformer time series",
    "vix",
    "volatility indices",
    "volatility surface",
    "vvix",
    "vxn"
  ];

  // Populate ticker twice for seamless scrolling
  if (ticker) {
    const content = topics.map(t => `<span>${t}</span>`).join('');
    ticker.innerHTML = content + content;
  }

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

  // --- Papers drawer ---

  function escapeHtml(s) {
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function timeAgo(isoString) {
    if (!isoString) return '';
    var diff = (Date.now() - new Date(isoString).getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
  }

  var papersLoaded = false;
  var toggle = document.getElementById('papers-toggle');
  var panel = document.getElementById('papers-panel');
  var list = document.getElementById('papers-list');

  function loadPapers() {
    if (papersLoaded) return;
    papersLoaded = true;
    fetch('/api/papers')
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.papers || d.papers.length === 0) {
          list.innerHTML = '<p class="papers-empty">No papers yet.</p>';
          return;
        }
        list.innerHTML = d.papers.map(function (p) {
          var cats = (p.categories || []).map(function (c) {
            return '<span class="paper-category">' + escapeHtml(c) + '</span>';
          }).join('');
          var time = p.fetched_at ? '<span class="paper-time">' + escapeHtml(timeAgo(p.fetched_at)) + '</span>' : '';
          return '<div class="paper-item">' +
            '<div class="paper-title"><a href="' + escapeHtml(p.url) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(p.title) + '</a></div>' +
            '<div class="paper-meta">' + cats + time + '</div>' +
            '</div>';
        }).join('');
      })
      .catch(function () {
        list.innerHTML = '<p class="papers-empty">Failed to load papers.</p>';
      });
  }

  if (toggle && panel) {
    toggle.addEventListener('click', function () {
      var expanded = toggle.getAttribute('aria-expanded') === 'true';
      toggle.setAttribute('aria-expanded', String(!expanded));
      panel.hidden = expanded;
      document.body.classList.toggle('papers-open', !expanded);
      if (!expanded) loadPapers();
    });
  }
})();
