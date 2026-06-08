"""GPU shader effects via moderngl — fragment shaders run on the frame.

Frames are uploaded as BGR textures (channel order doesn't matter for glitch
shaders), processed, and read back. The GL context is per-thread (preview thread
and render thread each get their own), created lazily. If GL is unavailable the
caller falls back to passthrough.
"""
from __future__ import annotations
import threading
import numpy as np

VERT = """
#version 330
in vec2 p; out vec2 uv;
void main(){ uv = p*0.5+0.5; gl_Position = vec4(p,0,1); }
"""

# each fragment samples with flipped v (st) so output orientation is correct.
# channels are BGR; .r=blue .b=red — fine for glitch aesthetics.
_HEAD = """
#version 330
in vec2 uv; out vec4 c;
uniform sampler2D tex0;
uniform float u_amount, u_p1, u_p2, u_time;
uniform vec2 u_res;
"""

SHADERS = {
"chroma": _HEAD + """
void main(){
  vec2 st=vec2(uv.x,1.0-uv.y);
  vec2 dir=st-0.5;
  float a=u_amount*(0.005+0.06*u_p1);
  float r=texture(tex0, st+dir*a).r;
  float g=texture(tex0, st).g;
  float b=texture(tex0, st-dir*a).b;
  c=vec4(r,g,b,1.0);
}""",
"kaleido": _HEAD + """
void main(){
  vec2 st=vec2(uv.x,1.0-uv.y);
  vec2 p=st-0.5;
  float ang=atan(p.y,p.x); float rad=length(p);
  float seg=3.14159/(2.0+floor(u_p1*8.0));
  ang=abs(mod(ang,2.0*seg)-seg);
  vec2 q=0.5+vec2(cos(ang),sin(ang))*rad;
  c=mix(texture(tex0,st), texture(tex0,q), u_amount);
}""",
"crt": _HEAD + """
void main(){
  vec2 st=vec2(uv.x,1.0-uv.y);
  vec2 cc=st-0.5;
  st += cc*dot(cc,cc)*(0.1+0.5*u_p1)*u_amount;
  vec4 col=texture(tex0, st);
  float scan=0.82+0.18*sin(st.y*u_res.y*3.14159);
  float vig=smoothstep(0.85,0.35,length(cc));
  col.rgb*=mix(1.0, scan*vig, u_amount);
  c=col;
}""",
"pixelate": _HEAD + """
void main(){
  vec2 st=vec2(uv.x,1.0-uv.y);
  float n=8.0+(1.0-u_p1)*240.0;
  vec2 q=(floor(st*n)+0.5)/n;
  c=mix(texture(tex0,st), texture(tex0,q), u_amount);
}""",
"bloom": _HEAD + """
void main(){
  vec2 st=vec2(uv.x,1.0-uv.y);
  vec4 base=texture(tex0,st);
  vec3 sum=vec3(0.0);
  float r=(1.0+u_p1*6.0)/u_res.x;
  for(int i=-4;i<=4;i++) for(int j=-4;j<=4;j++){
    sum += max(texture(tex0, st+vec2(float(i),float(j))*r).rgb-0.6, 0.0);
  }
  c=vec4(base.rgb + (sum/81.0)*u_amount*5.0, 1.0);
}""",
"displace": _HEAD + """
void main(){
  vec2 st=vec2(uv.x,1.0-uv.y);
  float a=u_amount*(0.01+0.09*u_p1);
  st.x += sin(st.y*20.0*(1.0+u_p2*5.0)+u_time*3.0)*a;
  st.y += cos(st.x*22.0+u_time*2.0)*a;
  c=texture(tex0, fract(st));
}""",
}
SHADER_NAMES = ("chroma", "kaleido", "crt", "pixelate", "bloom", "displace")

_local = threading.local()


class _Engine:
    def __init__(self):
        import moderngl
        self.mgl = moderngl
        self.ctx = moderngl.create_context(standalone=True)
        self.quad = self.ctx.buffer(np.array([-1, -1, 3, -1, -1, 3], dtype="f4").tobytes())
        self.progs = {}
        self.vaos = {}
        self.tex = None
        self.fbo = None
        self.size = (0, 0)

    def _prog(self, name):
        if name not in self.progs:
            p = self.ctx.program(vertex_shader=VERT, fragment_shader=SHADERS[name])
            self.progs[name] = p
            self.vaos[name] = self.ctx.vertex_array(p, [(self.quad, "2f", "p")])
        return self.progs[name], self.vaos[name]

    def run(self, name, frame, time, amount, p1, p2):
        h, w = frame.shape[:2]
        if self.size != (w, h):
            if self.tex:
                self.tex.release()
            if self.fbo:
                self.fbo.release()
            self.tex = self.ctx.texture((w, h), 3)
            self.tex.repeat_x = self.tex.repeat_y = True
            self.fbo = self.ctx.framebuffer(color_attachments=[self.ctx.texture((w, h), 3)])
            self.size = (w, h)
        self.tex.write(np.ascontiguousarray(frame).tobytes())
        prog, vao = self._prog(name)
        for u, val in (("u_time", float(time)), ("u_amount", float(amount)),
                       ("u_p1", float(p1)), ("u_p2", float(p2))):
            m = prog.get(u, None)
            if m is not None:
                m.value = val
        m = prog.get("u_res", None)
        if m is not None:
            m.value = (float(w), float(h))
        self.tex.use(0)
        m = prog.get("tex0", None)
        if m is not None:
            m.value = 0
        self.fbo.use()
        vao.render(mode=self.mgl.TRIANGLES)
        data = np.frombuffer(self.fbo.read(components=3), dtype=np.uint8).reshape(h, w, 3)
        return np.ascontiguousarray(data)


def _engine():
    e = getattr(_local, "engine", None)
    if e is None:
        e = _Engine()
        _local.engine = e
    return e


def register_shader(name: str, fragment_src: str):
    """Add a custom GLSL fragment shader (use _HEAD-style uniforms)."""
    SHADERS[name] = fragment_src


def available() -> bool:
    try:
        _engine()
        return True
    except Exception:
        return False


def process(name, frame, time=0.0, amount=1.0, p1=0.5, p2=0.5):
    return _engine().run(name, frame, time, amount, p1, p2)
