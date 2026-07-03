# typed: false
# frozen_string_literal: true

class Aism < Formula
  desc "Browse, search, and resume Claude Code and opencode sessions with fzf"
  homepage "https://github.com/Yarden-zamir/aism"
  url "{{URL}}"
  sha256 "{{SHA256}}"
  license "MIT"

  depends_on "fzf"
  depends_on "ripgrep"
  depends_on "uv"

  def install
    # Zero-dependency pure-stdlib package: uv provides and manages the Python
    # runtime, so there is no python formula dependency.
    libexec.install "aism"
    (bin/"aism").write <<~SH
      #!/bin/bash
      export PYTHONPATH="#{libexec}${PYTHONPATH:+:$PYTHONPATH}"
      exec "#{formula_opt_bin("uv")}/uv" run --no-project --python 3.12 -m aism "$@"
    SH
    chmod 0755, bin/"aism"
  end

  test do
    assert_match "usage: aism", shell_output("#{bin}/aism --help")
  end
end
