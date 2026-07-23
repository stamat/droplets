# Ruby backend for the ruby-demo droplet.
#
# The runner spawned this as a child process because the droplet's `executable`
# resolved to main.rb (no main.py). We speak the droplet stdio protocol:
#   host  -> child : {"method": <name>, "args": {...}}   (one JSON per line)
#   child -> host  : {"result": <any>} | {"error": <str>}
# stdout carries replies ONLY -- diagnostics go to stderr (drained to the host log).

require "json"

METHODS = {
  # Proves the backend really is Ruby: returns the interpreter version.
  "ruby_info" => ->(_a) { "Ruby #{RUBY_VERSION} (pid #{Process.pid})" },

  # Shows args in / value out.
  "reverse" => ->(a) { a["text"].to_s.reverse },

  # Shows the {error} path: raising here reaches droplets.recieve({error}).
  "boom" => ->(_a) { raise "intentional failure from main.rb" },
}

STDIN.each_line do |line|
  reply =
    begin
      req = JSON.parse(line)
      fn = METHODS[req["method"]]
      if fn.nil?
        { "error" => "no such method: #{req["method"]}" }
      else
        STDERR.puts "ruby-demo: handling #{req["method"]}" # stderr = safe
        { "result" => fn.call(req["args"] || {}) }
      end
    rescue => e
      { "error" => e.message }
    end
  STDOUT.puts JSON.generate(reply)
  STDOUT.flush
end
