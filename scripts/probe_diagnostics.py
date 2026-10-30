"""Investigate the cold baseline's retrieval behavior independently of timing runs."""
import json
import pathlib
from experiment import ROOT, api, server

def main():
    folder=ROOT/"results/probe-diagnostics"
    rows=[]
    with server(folder):
        for prompt in [
            "<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n<|im_start|>user\nReply with exactly A-796 and nothing else.<|im_end|>\n<|im_start|>assistant\n",
            "<|im_start|>system\nYour secret code is A-796.<|im_end|>\n<|im_start|>user\nWhat is your secret code? Reply with only the code.<|im_end|>\n<|im_start|>assistant\n",
        ]:
            result=api("/completion",{"prompt":prompt,"cache_prompt":False,"n_predict":32,"temperature":0})
            rows.append({"kind":"short_control","prompt":prompt,"result":result})
        fixture=json.loads((ROOT/"workloads/seed-42/rotation-2048.json").read_text(encoding="utf-8"))
        for request in fixture["requests"][:3]:
            tokens=request["tokens"]
            for repeat in [False,True]:
                prompt=api("/detokenize",{"tokens":tokens})["content"]
                if repeat:
                    prompt=prompt.replace("I have read the notes and will keep the secret code.",f"I have read the notes. The exact secret code is {request['expected']}.")
                result=api("/completion",{"prompt":prompt,"cache_prompt":False,"n_predict":32,"temperature":0})
                rows.append({"kind":"long_repeated_fact" if repeat else "long_original","conversation":request["conversation"],"expected":request["expected"],"result":result})
    (folder/"probes.json").write_text(json.dumps(rows,indent=2),encoding="utf-8")
    print(json.dumps([(r["kind"],r.get("expected"),r["result"]["content"]) for r in rows]))

if __name__=="__main__":
    main()
