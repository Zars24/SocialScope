/* SocialScope front end: theme, navigation, analyzer form, story player, motion.
   Everything degrades: no JS means no `has-motion` class, so all content stays visible. */
(function () {
  "use strict";

  var root = document.documentElement;
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function all(selector, scope) {
    return Array.prototype.slice.call((scope || document).querySelectorAll(selector));
  }

  /* ---- Theme ------------------------------------------------------------ */

  var themeToggle = document.querySelector("[data-theme-toggle]");

  function syncTheme() {
    if (!themeToggle) return;
    var light = root.dataset.theme === "light";
    themeToggle.setAttribute("aria-pressed", light ? "true" : "false");
  }

  if (themeToggle) {
    syncTheme();
    themeToggle.addEventListener("click", function () {
      var next = root.dataset.theme === "light" ? "dark" : "light";
      root.dataset.theme = next;
      try {
        localStorage.setItem("socialscope-theme", next);
      } catch (error) {
        /* storage disabled: theme still applies for this page */
      }
      syncTheme();
    });
  }

  /* ---- Mobile navigation ------------------------------------------------ */

  var navToggle = document.querySelector("[data-nav-toggle]");
  var nav = document.querySelector("[data-nav]");

  function setNav(open) {
    if (!nav || !navToggle) return;
    nav.classList.toggle("is-open", open);
    navToggle.setAttribute("aria-expanded", open ? "true" : "false");
    root.classList.toggle("nav-open", open);
  }

  if (nav && navToggle) {
    navToggle.addEventListener("click", function () {
      setNav(!nav.classList.contains("is-open"));
    });
    all("a", nav).forEach(function (link) {
      link.addEventListener("click", function () {
        setNav(false);
      });
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && nav.classList.contains("is-open")) {
        setNav(false);
        navToggle.focus();
      }
    });
    document.addEventListener("click", function (event) {
      if (!nav.classList.contains("is-open")) return;
      if (nav.contains(event.target) || navToggle.contains(event.target)) return;
      setNav(false);
    });
    window.addEventListener("resize", function () {
      if (window.innerWidth > 860) setNav(false);
    });
  }

  /* ---- Analyzer form ---------------------------------------------------- */

  var PLATFORM_LABEL = { tiktok: "TikTok", instagram: "Instagram" };

  all("[data-analyzer]").forEach(function (form) {
    var input = form.querySelector("[data-analyzer-input]");
    var submit = form.querySelector("[data-submit]");
    var detect = form.querySelector("[data-platform]");
    var label = form.querySelector(".btn-label");

    function detectPlatform() {
      if (!detect || !input) return;
      var value = input.value.toLowerCase();
      var platform = "";
      if (value.indexOf("tiktok") !== -1) platform = "tiktok";
      else if (value.indexOf("instagram") !== -1) platform = "instagram";
      detect.dataset.platform = platform;
      detect.textContent = platform ? PLATFORM_LABEL[platform] : "";
    }

    if (input) {
      input.addEventListener("input", detectPlatform);
      detectPlatform();
    }

    form.addEventListener("submit", function () {
      if (submit) submit.disabled = true;
      form.classList.add("is-busy");
      if (label && label.dataset.labelBusy) label.textContent = label.dataset.labelBusy;
    });
  });

  /* Restore the button when the browser returns from the bfcache. */
  window.addEventListener("pageshow", function (event) {
    if (!event.persisted) return;
    all("[data-analyzer]").forEach(function (form) {
      form.classList.remove("is-busy");
      var submit = form.querySelector("[data-submit]");
      var label = form.querySelector(".btn-label");
      if (submit) submit.disabled = false;
      if (label && label.dataset.labelDefault) label.textContent = label.dataset.labelDefault;
    });
  });

  /* ---- Result tabs ------------------------------------------------------ */

  all("[data-tabs]").forEach(function (tabs) {
    var buttons = all("[data-tab]", tabs);
    var scope = tabs.parentElement || tabs;
    var panels = all("[data-panel]", scope);

    function select(button) {
      buttons.forEach(function (item) {
        var active = item === button;
        item.setAttribute("aria-selected", active ? "true" : "false");
        item.classList.toggle("is-active", active);
      });
      panels.forEach(function (panel) {
        panel.classList.toggle("is-active", panel.dataset.panel === button.dataset.tab);
      });
    }

    buttons.forEach(function (button, i) {
      button.addEventListener("click", function () {
        select(button);
      });
      button.addEventListener("keydown", function (event) {
        var step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
        if (!step) return;
        event.preventDefault();
        var next = buttons[(i + step + buttons.length) % buttons.length];
        next.focus();
        select(next);
      });
    });
  });

  /* ---- Story player ----------------------------------------------------- */

  all("[data-story-player]").forEach(function (player) {
    var slides = all("[data-story-slide]", player);
    if (!slides.length) return;

    var fills = all(".story-seg-fill", player);
    var thumbs = all("[data-story-goto]", player);
    var caption = player.querySelector("[data-story-caption]");
    var timeEl = player.querySelector("[data-story-time]");
    var link = player.querySelector("[data-story-link]");
    var typeEl = player.querySelector("[data-story-detail-type]");
    var detailTime = player.querySelector("[data-story-detail-time]");
    var detailDur = player.querySelector("[data-story-detail-dur]");
    var detailDurDot = player.querySelector("[data-story-detail-dur-dot]");
    var mediaLink = player.querySelector("[data-story-media]");
    var pauseBtn = player.querySelector("[data-story-pause]");
    var muteBtn = player.querySelector("[data-story-mute]");

    var index = 0;
    var playing = true;
    var muted = true;
    var duration = 5000;
    var startedAt = 0;
    var elapsed = 0;
    var frame = 0;

    function slideDuration(slide) {
      var video = slide.querySelector("[data-story-video]");
      if (video && isFinite(video.duration) && video.duration > 0) return video.duration * 1000;
      var value = parseFloat(slide.dataset.duration);
      return (isFinite(value) && value > 0 ? value : 5) * 1000;
    }

    function setFill(i, ratio) {
      if (!fills[i]) return;
      fills[i].style.transform = "scaleX(" + ratio + ")";
    }

    function stopTimer() {
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
      if (playing && startedAt) {
        elapsed += performance.now() - startedAt;
        startedAt = 0;
      }
    }

    function tick(now) {
      if (!playing) return;
      if (!startedAt) startedAt = now;
      var ratio = Math.min(1, (elapsed + (now - startedAt)) / duration);
      setFill(index, ratio);
      if (ratio >= 1) {
        go(index + 1);
        return;
      }
      frame = requestAnimationFrame(tick);
    }

    function startTimer() {
      if (!playing) return;
      startedAt = 0;
      frame = requestAnimationFrame(tick);
    }

    function go(target) {
      stopTimer();
      elapsed = 0;
      startedAt = 0;

      if (target >= slides.length) {
        playing = false;
        setFill(slides.length - 1, 1);
        syncPause();
        return;
      }
      if (target < 0) target = 0;

      index = target;
      slides.forEach(function (slide, i) {
        var active = i === index;
        slide.classList.toggle("is-active", active);
        slide.setAttribute("aria-hidden", active ? "false" : "true");
        var video = slide.querySelector("[data-story-video]");
        if (video) {
          if (active) {
            video.muted = muted;
            var played = video.play();
            if (played && played.catch) played.catch(function () {});
          } else {
            video.pause();
            try {
              video.currentTime = 0;
            } catch (error) {
              /* metadata not ready */
            }
          }
        }
      });

      thumbs.forEach(function (thumb, i) {
        var active = i === index;
        thumb.classList.toggle("is-active", active);
        thumb.setAttribute("aria-pressed", active ? "true" : "false");
      });

      fills.forEach(function (fill, i) {
        setFill(i, i < index ? 1 : 0);
      });

      var slide = slides[index];
      if (caption) {
        var template = caption.dataset.template || "{n}";
        caption.textContent = template.replace("{n}", String(index + 1));
      }
      if (timeEl && slide.dataset.taken) timeEl.textContent = slide.dataset.taken;
      if (link && slide.dataset.permalink) link.href = slide.dataset.permalink;

      // Per-item detail row: type, upload time, duration, and the media link.
      if (typeEl && slide.dataset.typeLabel) typeEl.textContent = slide.dataset.typeLabel;
      if (detailTime && slide.dataset.taken) detailTime.textContent = slide.dataset.taken;
      if (detailDur) {
        var durText = slide.dataset.durationText || "";
        detailDur.textContent = durText;
        var isVideo = slide.dataset.type === "video";
        detailDur.hidden = !isVideo;
        if (detailDurDot) detailDurDot.hidden = !isVideo;
      }
      if (mediaLink && slide.dataset.media) mediaLink.href = slide.dataset.media;

      duration = slideDuration(slide);
      startTimer();
    }

    function syncPause() {
      if (!pauseBtn) return;
      pauseBtn.setAttribute("aria-pressed", playing ? "false" : "true");
      var pausedLabel = pauseBtn.dataset.labelPlay;
      var playingLabel = pauseBtn.dataset.labelPause;
      if (playingLabel && pausedLabel) {
        pauseBtn.setAttribute("aria-label", playing ? playingLabel : pausedLabel);
      }
    }

    function togglePause() {
      playing = !playing;
      if (playing) {
        if (index >= slides.length - 1 && elapsed >= duration) elapsed = 0;
        var video = slides[index].querySelector("[data-story-video]");
        if (video) {
          var played = video.play();
          if (played && played.catch) played.catch(function () {});
        }
        startTimer();
      } else {
        stopTimer();
        var current = slides[index].querySelector("[data-story-video]");
        if (current) current.pause();
      }
      syncPause();
    }

    if (pauseBtn) {
      pauseBtn.addEventListener("click", togglePause);
    }

    if (muteBtn) {
      muteBtn.addEventListener("click", function () {
        muted = !muted;
        muteBtn.setAttribute("aria-pressed", muted ? "false" : "true");
        if (muteBtn.dataset.labelMuted && muteBtn.dataset.labelSound) {
          muteBtn.setAttribute("aria-label", muted ? muteBtn.dataset.labelMuted : muteBtn.dataset.labelSound);
        }
        all("[data-story-video]", player).forEach(function (video) {
          video.muted = muted;
        });
      });
    }

    var prevBtn = player.querySelector("[data-story-prev]");
    var nextBtn = player.querySelector("[data-story-next]");
    if (prevBtn) prevBtn.addEventListener("click", function () { go(index - 1); });
    if (nextBtn) nextBtn.addEventListener("click", function () { go(index + 1); });

    thumbs.forEach(function (thumb) {
      thumb.addEventListener("click", function () {
        playing = true;
        syncPause();
        go(parseInt(thumb.dataset.storyGoto, 10) || 0);
      });
    });

    player.addEventListener("keydown", function (event) {
      if (event.key === "ArrowRight") {
        event.preventDefault();
        go(index + 1);
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        go(index - 1);
      } else if (event.key === " " || event.key === "Spacebar") {
        event.preventDefault();
        togglePause();
      }
    });

    all("[data-story-video]", player).forEach(function (video) {
      video.addEventListener("loadedmetadata", function () {
        if (video.closest("[data-story-slide]") === slides[index]) duration = slideDuration(slides[index]);
      });
    });

    syncPause();
    go(0);
  });

  /* ---- Motion: GSAP + ScrollTrigger + Lenis ----------------------------- */

  var gsap = window.gsap;
  var ScrollTrigger = window.ScrollTrigger;
  var Lenis = window.Lenis;

  if (!gsap || reduceMotion) return;

  if (ScrollTrigger) gsap.registerPlugin(ScrollTrigger);
  root.classList.add("has-motion");

  var heroLines = all("[data-hero-line]");
  if (heroLines.length) {
    gsap.set(heroLines, { yPercent: 110 });
    gsap.to(heroLines, {
      yPercent: 0,
      duration: 0.9,
      ease: "power3.out",
      stagger: 0.08,
      delay: 0.05,
      overwrite: true
    });
  }

  var revealTargets = all("[data-reveal], [data-stagger] > *");
  if (revealTargets.length) {
    gsap.set(revealTargets, { opacity: 0, y: 16 });
    if (ScrollTrigger) {
      ScrollTrigger.batch(revealTargets, {
        start: "top 92%",
        once: true,
        onEnter: function (batch) {
          gsap.to(batch, {
            opacity: 1,
            y: 0,
            duration: 0.7,
            ease: "power2.out",
            stagger: 0.07,
            overwrite: true
          });
        }
      });
    } else {
      gsap.to(revealTargets, { opacity: 1, y: 0, duration: 0.6, stagger: 0.05 });
    }
  }

  if (Lenis) {
    // `lerp` tracks the wheel immediately; `duration` mode eases over a fixed
    // window and is the main reason scrolling felt held back. Pick one, not both.
    // `autoRaf: false` because GSAP's ticker drives the frame below; without that
    // guarantee Lenis would own a second rAF loop and drift from ScrollTrigger.
    var lenis = new Lenis({
      lerp: 0.1,
      smoothWheel: true,
      wheelMultiplier: 1,
      touchMultiplier: 1.5,
      syncTouch: false,
      autoRaf: false
    });

    if (ScrollTrigger) lenis.on("scroll", ScrollTrigger.update);

    // Always drive Lenis, not only when ScrollTrigger exists.
    gsap.ticker.add(function (time) {
      lenis.raf(time * 1000);
    });
    gsap.ticker.lagSmoothing(0);

    document.addEventListener("click", function (event) {
      var anchor = event.target.closest ? event.target.closest('a[href^="#"]') : null;
      if (!anchor) return;
      var target = document.querySelector(anchor.getAttribute("href"));
      if (!target) return;
      event.preventDefault();
      lenis.scrollTo(target, { offset: -72 });
    });

    // The document grew after fonts/embeds settled.
    if (ScrollTrigger) ScrollTrigger.refresh();
  }
})();
