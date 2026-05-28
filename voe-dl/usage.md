# voe-dl

A Python-based downloader for videos https://github.com/p4ul17/voe-dl

## 📥 How to Use `voe-dl`

### Download Single Video

```bash
voe-dl -u https://voe.sx/yourvideo
```

### Download from a list (batch)

Create a `links.txt` file:

```
https://voe.sx/xxxxxxx
https://voe.sx/yyyyyyy
```

Run:

```bash
voe-dl -l links.txt -w 8
```

add the `-w` option to set number of parallel workers (Default is 4)

## 🆘 Help

Run:

```bash
voe-dl -h
```

This will print all available options, arguments, and descriptions.
