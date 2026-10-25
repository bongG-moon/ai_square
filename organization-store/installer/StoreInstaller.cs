// Per-user optional extension installer. It never starts the common app,
// changes Claude settings, or removes extension-data/downloaded skills.
using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;

internal static class StoreInstaller {
    const string Id = "pt-ai-square.store", Product = "AX.OrganizationStore", Owner = ".ax-extension-owner.json";
    const int Limit = 64 * 1024 * 1024;
    const string ExpectedPackageHash = "__PACKAGE_SHA256__";
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 2 * 1024 * 1024, RecursionLimit = 32 };
    static readonly UTF8Encoding Utf8 = new UTF8Encoding(false, true);
    static readonly Regex Digest = new Regex("^[0-9a-f]{64}$");
    static readonly Regex Reserved = new Regex("^(con|prn|aux|nul|com[1-9]|lpt[1-9])$", RegexOptions.IgnoreCase);
    static Dictionary<string, object> Obj(object value) {
        var result = value as Dictionary<string, object>;
        if (result == null) throw new InvalidDataException("설치 정보의 형식이 올바르지 않습니다.");
        return result;
    }
    static string Text(Dictionary<string, object> value, string key) {
        object item; return value.TryGetValue(key, out item) ? item as string : null;
    }
    static string Sha(byte[] value) { using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(value)).Replace("-", "").ToLowerInvariant(); }
    static byte[] Read(string path, int limit) {
        NoLinks(path);
        using (var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read)) {
            if (file.Length > limit) throw new InvalidDataException("파일 크기가 지원 범위를 넘었습니다.");
            using (var output = new MemoryStream()) { byte[] block=new byte[65536];int count;while((count=file.Read(block,0,block.Length))>0){if(output.Length+count>limit)throw new InvalidDataException("파일 크기가 변경되었습니다.");output.Write(block,0,count);}return output.ToArray(); }
        }
    }
    static Dictionary<string, object> Decode(byte[] value) { return Obj(Json.DeserializeObject(Utf8.GetString(value))); }
    static byte[] Encode(object value) { return Utf8.GetBytes(Json.Serialize(value)); }
    static byte[] Connection(string path) {
        // Only a public origin is accepted. Do not deserialize arbitrary config,
        // import credentials, or echo rejected file contents in the error dialog.
        try {
            string raw=Utf8.GetString(Read(Full(path),4096));
            string jsonString="\"(?:[^\"\\\\\\x00-\\x1f]|\\\\[\"\\\\/bfnrt]|\\\\u[0-9a-fA-F]{4})*\"";
            string version="\"schemaVersion\"\\s*:\\s*1", url="\"baseUrl\"\\s*:\\s*"+jsonString;
            if(!Regex.IsMatch(raw,"\\A\\s*\\{\\s*(?:"+version+"\\s*,\\s*"+url+"|"+url+"\\s*,\\s*"+version+")\\s*\\}\\s*\\z"))
                throw new InvalidDataException();
            var value=Decode(Utf8.GetBytes(raw)); string supplied=Text(value,"baseUrl"); Uri uri;
            if(String.IsNullOrEmpty(supplied)||supplied.Length>500||supplied.Any(c=>c<=32)||supplied.Contains("\\")||supplied.Contains("@")||
                !Regex.IsMatch(supplied,"\\Ahttps?://[^/?#]+/?\\z",RegexOptions.IgnoreCase)||
                !Uri.TryCreate(supplied,UriKind.Absolute,out uri)||String.IsNullOrEmpty(uri.Host)||uri.UserInfo!=""||uri.Query!=""||uri.Fragment!=""||uri.AbsolutePath!="/")
                throw new InvalidDataException();
            string origin=uri.GetLeftPart(UriPartial.Authority).ToLowerInvariant();
            return Encode(new Dictionary<string,object>{{"schemaVersion",1},{"baseUrl",origin}});
        } catch(Exception error) {
            if(error is OutOfMemoryException||error is StackOverflowException)throw;
            throw new InvalidDataException("다운로드한 서버 주소 파일(connection.json)을 확인할 수 없습니다. 웹에서 ZIP을 다시 내려받고 모두 압축 해제해 주세요.");
        }
    }
    static string Full(string path) {
        string full = Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        if (full.Length < 4 || String.Equals(full, Path.GetPathRoot(full).TrimEnd('\\'), StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("드라이브 전체를 설치 위치로 사용할 수 없습니다.");
        // Extended paths avoid the machine-wide LongPathsEnabled dependency,
        // including long user profile names and nested portable test folders.
        if(full.StartsWith("\\\\?\\",StringComparison.Ordinal))return full;
        if(full.StartsWith("\\\\",StringComparison.Ordinal))return "\\\\?\\UNC\\"+full.Substring(2);
        return "\\\\?\\"+full;
    }
    static void NoLinks(string path) {
        var current = Path.GetFullPath(path);
        while (!String.IsNullOrEmpty(current)) {
            try { if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0) throw new InvalidDataException("연결된 폴더나 링크에는 설치하거나 삭제하지 않습니다."); }
            catch (FileNotFoundException) {} catch (DirectoryNotFoundException) {}
            string parent = Path.GetDirectoryName(current); if (parent == current) break; current = parent;
        }
    }
    static string Relative(string value) {
        if (String.IsNullOrEmpty(value) || value.Length > 220 || value.IndexOf('\\') >= 0 || value.IndexOf(':') >= 0 || value.Any(c => c < 32))
            throw new InvalidDataException("패키지 파일 경로가 올바르지 않습니다.");
        foreach (string part in value.Split('/'))
            if (part == "" || part == "." || part == ".." || part.EndsWith(".") || part.EndsWith(" ") || Reserved.IsMatch(part.Split('.')[0]))
                throw new InvalidDataException("패키지 경로를 벗어나는 파일은 설치하지 않습니다.");
        return value;
    }
    static string Within(string root, string name) {
        string file = Path.GetFullPath(Path.Combine(root, Relative(name).Replace('/', Path.DirectorySeparatorChar)));
        if (!file.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("설치 범위를 벗어난 경로입니다.");
        NoLinks(file); return file;
    }
    static void WriteAtomic(string target, byte[] bytes) {
        if(Path.GetFileName(target)==Owner && bytes.Length>2*1024*1024)throw new InvalidDataException("보관된 설치 기록이 너무 큽니다. 스토어 확장을 제거한 뒤 다시 설치해 주세요. 사용자 자료는 유지됩니다.");
        NoLinks(target);
        // Same-volume scratch lives outside the registered extension. A hard
        // kill while writing a temporary file must not poison its exact tree.
        string scratch = Path.GetDirectoryName(Path.GetDirectoryName(Path.GetDirectoryName(target)));
        string temporary = Path.Combine(scratch, ".store-write-" + Guid.NewGuid().ToString("N"));NoLinks(temporary);
        try {
            using (var file = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None)) { file.Write(bytes, 0, bytes.Length); file.Flush(true); }
            NoLinks(target);
            if (File.Exists(target)) File.Replace(temporary, target, null); else File.Move(temporary, target);
        } finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }
    static void WriteConnection(string target, byte[] bytes) {
        for(int attempt=0;;attempt++) {
            try {
                if(File.Exists(target)&&Read(target,4096).SequenceEqual(bytes))return;
                WriteAtomic(target,bytes);return;
            } catch(IOException error) {
                // A background file reader can briefly hold the previous
                // preset on Windows. Never retry access-denied or change ACLs.
                int code=error.HResult&0xffff;
                if(attempt>=3||(code!=32&&code!=33&&code!=1175))throw;
                Thread.Sleep(40*(attempt+1));
            }
        }
    }
    static void Host(string supplied) {
        string host = Full(supplied); NoLinks(host);
        if (Directory.Exists(host)) {
            // An explicit source checkout is useful for a portable developer run.
            var api = Utf8.GetString(Read(Path.Combine(host, "local_app", "extensions.py"), 256 * 1024));
            var ui = Utf8.GetString(Read(Path.Combine(host, "local_app", "web", "extensions.js"), 256 * 1024));
            if (!api.Contains("HOST_API = 1") || !ui.Contains("WorkspaceExtensions")) throw new InvalidDataException("확장 API 1을 지원하는 AX Workspace가 필요합니다.");
            return;
        }
        if (!Regex.IsMatch(Path.GetFileName(host), "^AX-Workspace(?:-[0-9]+\\.[0-9]+\\.[0-9]+)?\\.exe$", RegexOptions.IgnoreCase))
            throw new InvalidDataException("AX Workspace 실행 파일을 확인해 주세요.");
        // Read embedded metadata without executing the host or its entry point.
        var assembly = Assembly.ReflectionOnlyLoad(Read(host,256*1024*1024));
        using (var stream = assembly.GetManifestResourceStream("WorkspacePayload.manifest.tsv")) {
            if (stream == null || stream.Length > 4 * 1024 * 1024) throw new InvalidDataException("이 AX Workspace는 확장 연결부를 지원하지 않습니다. 확장 지원 빌드를 설치해 주세요.");
            using (var reader = new StreamReader(stream, Utf8)) {
                string manifest = reader.ReadToEnd().Replace("\r\n", "\n");
                if (!manifest.Contains("\tCompany-Workspace/local_app/extensions.py\n") || !manifest.Contains("\tCompany-Workspace/local_app/web/extensions.js\n"))
                    throw new InvalidDataException("확장 연결부가 포함된 AX Workspace 빌드가 필요합니다. 같은 버전 번호라도 기존 빌드는 지원하지 않을 수 있습니다.");
            }
        }
    }
    sealed class Package {
        public byte[] Manifest; public Dictionary<string, object> Value, Files; public Dictionary<string, byte[]> Bytes;
        public string Build;
    }
    static Package Load(string zipPath) {
        byte[] archive = Read(zipPath, Limit);
        if (Sha(archive) != ExpectedPackageHash) throw new InvalidDataException("패키지 해시가 설치 프로그램과 다릅니다. 설치 파일을 다시 받아 주세요.");
        var bytes = new Dictionary<string, byte[]>(StringComparer.OrdinalIgnoreCase); long total = 0;
        using (var input = new MemoryStream(archive)) using (var zip = new ZipArchive(input, ZipArchiveMode.Read)) {
            if (zip.Entries.Count < 3 || zip.Entries.Count > 513) throw new InvalidDataException("패키지 파일 수가 올바르지 않습니다.");
            foreach (var entry in zip.Entries) {
                string name = Relative(entry.FullName);
                int unixMode = (entry.ExternalAttributes >> 16) & 0xf000;
                if (unixMode != 0 && unixMode != 0x8000 || (entry.ExternalAttributes & 0x400) != 0 || bytes.ContainsKey(name))
                    throw new InvalidDataException("링크 또는 중복 파일이 포함된 패키지는 설치하지 않습니다.");
                total += entry.Length; if (entry.Length > Limit || total > Limit) throw new InvalidDataException("패키지가 너무 큽니다.");
                using (var source = entry.Open()) using (var output = new MemoryStream()) {
                    byte[] block = new byte[65536]; int count;
                    while ((count = source.Read(block, 0, block.Length)) > 0) { output.Write(block, 0, count); if (output.Length > entry.Length || output.Length > Limit) throw new InvalidDataException("압축 파일의 크기가 올바르지 않습니다."); }
                    bytes.Add(name, output.ToArray());
                }
            }
        }
        byte[] manifest; if (!bytes.TryGetValue("extension.json", out manifest) || manifest.Length > 128 * 1024) throw new InvalidDataException("확장 등록 정보가 없습니다.");
        var value = Decode(manifest);
        if (Text(value, "id") != Id || Convert.ToInt32(value["schemaVersion"]) != 1 || Convert.ToInt32(value["hostApi"]) != 1)
            throw new InvalidDataException("호환되지 않는 확장 패키지입니다.");
        var files = Obj(value["files"]); string entrypoint = Relative(Text(value, "entrypoint"));
        string[] parts = entrypoint.Split('/');
        if (parts.Length != 3 || parts[0] != "packages" || !Digest.IsMatch(parts[1]) || parts[2] != "worker.py" || Text(value, "ui") != "packages/" + parts[1] + "/ui.html")
            throw new InvalidDataException("확장 패키지 버전 경로가 올바르지 않습니다.");
        string prefix = "packages/" + parts[1] + "/";
        if (files.Count < 2 || files.Count > 512 || bytes.Count != files.Count + 1) throw new InvalidDataException("파일 선언과 실제 패키지가 다릅니다.");
        foreach (var item in files) {
            string name = Relative(item.Key); string digest = item.Value as string;
            if (!name.StartsWith(prefix, StringComparison.Ordinal) || !Digest.IsMatch(digest ?? "") || !bytes.ContainsKey(name) || Sha(bytes[name]) != digest)
                throw new InvalidDataException("확장 파일 검증에 실패했습니다.");
        }
        string fingerprint = String.Join("\n", files.OrderBy(x => x.Key, StringComparer.Ordinal).Select(x => x.Key.Substring(prefix.Length) + "\t" + (string)x.Value)) + "\n";
        if (Sha(Utf8.GetBytes(fingerprint)) != parts[1]) throw new InvalidDataException("확장 빌드 식별자가 일치하지 않습니다.");
        return new Package {Manifest=manifest, Value=value, Files=files, Bytes=bytes, Build=parts[1]};
    }
    static Dictionary<string, object> Owned(string directory, Package recovery = null) {
        var marker = Decode(Read(Path.Combine(directory, Owner), 2 * 1024 * 1024));
        if (Text(marker, "product") != Product || Text(marker, "id") != Id || Convert.ToInt32(marker["schemaVersion"]) != 1)
            throw new InvalidDataException("이 설치 프로그램이 만든 폴더가 아닙니다. 기존 파일은 변경하지 않았습니다.");
        var packages = Obj(marker["packages"]); if (packages.Count < 1 || packages.Count > 64) throw new InvalidDataException("기존 설치 기록을 확인할 수 없습니다.");
        var expected = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        bool currentKnown = false; string currentHash = Sha(Read(Path.Combine(directory, "extension.json"), 128 * 1024));
        foreach (var package in packages) {
            if (!Digest.IsMatch(package.Key)) throw new InvalidDataException("기존 버전 경로를 확인할 수 없습니다.");
            var data=Obj(package.Value); currentKnown |= Text(data,"manifestSha256")==currentHash;
            foreach (var file in Obj(data["files"])) {
                string name=Relative(file.Key), digest=file.Value as string;
                if (!name.StartsWith("packages/"+package.Key+"/",StringComparison.Ordinal) || !Digest.IsMatch(digest??"") || expected.ContainsKey(name))
                    throw new InvalidDataException("기존 설치 소유권 정보를 확인할 수 없습니다.");
                expected.Add(name,digest);
            }
        }
        if (!currentKnown) throw new InvalidDataException("등록 정보가 변경되어 기존 파일을 유지했습니다.");
        var discovered = FilesIn(directory);
        bool recoverOrphan=false;
        if (!discovered.SetEquals(expected.Keys.Concat(new[]{Owner,"extension.json"}))) {
            // A killed updater may have moved the fully written immutable
            // package before committing its ownership record. Only the exact
            // current, outer-checksummed installer payload can recover it.
            if(recovery==null || packages.ContainsKey(recovery.Build) ||
                !discovered.SetEquals(expected.Keys.Concat(recovery.Files.Keys).Concat(new[]{Owner,"extension.json"})))
                throw new InvalidDataException("설치 폴더에 다른 파일이 있습니다. 기존 파일을 유지했습니다.");
            recoverOrphan=true;
        }
        foreach(var file in expected) if(Sha(Read(Within(directory,file.Key),Limit))!=file.Value) throw new InvalidDataException("설치 파일이 변경되었습니다. 기존 파일을 유지했습니다.");
        if(recoverOrphan){
            foreach(var file in recovery.Files)if(Sha(Read(Within(directory,file.Key),Limit))!=(string)file.Value)
                throw new InvalidDataException("중단된 설치 파일이 원본과 다릅니다. 기존 버전을 유지했습니다.");
            packages.Add(recovery.Build,new Dictionary<string,object>{{"manifestSha256",Sha(recovery.Manifest)},{"files",recovery.Files}});
            WriteAtomic(Path.Combine(directory,Owner),Encode(marker));
        }
        return marker;
    }
    static HashSet<string> FilesIn(string directory) {
        var found = new HashSet<string>(StringComparer.OrdinalIgnoreCase); var todo = new Stack<string>(); todo.Push(directory); int count=0;
        while(todo.Count>0) foreach(string path in Directory.EnumerateFileSystemEntries(todo.Pop())) {
            if(++count>34000)throw new InvalidDataException("설치 폴더가 너무 큽니다.");NoLinks(path);
            if(Directory.Exists(path))todo.Push(path);else found.Add(path.Substring(directory.Length+1).Replace('\\','/'));
        }
        return found;
    }
    static void RemoveFiles(string root, IEnumerable<string> names) {
        // Delete only the verified allowlist; never recursively remove a root.
        foreach(string name in names) {string path=Within(root,name);if(File.Exists(path))File.Delete(path);}
        var dirs=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach(string name in names) {string dir=Path.GetDirectoryName(Within(root,name));while(dir!=root&&dir.StartsWith(root+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)){dirs.Add(dir);dir=Path.GetDirectoryName(dir);}}
        foreach(string dir in dirs.OrderByDescending(x=>x.Length)) {NoLinks(dir);if(Directory.Exists(dir)&&!Directory.EnumerateFileSystemEntries(dir).Any())Directory.Delete(dir,false);}
    }
    static void Install(string parent, string zip, string host, string connectionPath=null) {
        // Validate the optional preset and its destination before any install
        // mutation. The immutable package and its pinned hash remain unchanged.
        byte[] preset=connectionPath==null?null:Connection(connectionPath);
        Host(host);var package=Load(zip);parent=Full(parent);NoLinks(parent);
        string presetTarget=Path.Combine(parent,"extension-data",Id,"connection.json");
        if(preset!=null){NoLinks(presetTarget);if(Directory.Exists(presetTarget)||File.Exists(Path.GetDirectoryName(presetTarget))||File.Exists(Path.Combine(parent,"extension-data")))throw new InvalidDataException("서버 주소를 저장할 폴더를 확인해 주세요.");}
        string extension=Path.Combine(parent,"extensions",Id);NoLinks(extension);
        Dictionary<string,object> marker=null;
        if(Directory.Exists(extension))marker=Owned(extension,package);
        else if(File.Exists(extension))throw new InvalidDataException("설치 경로에 파일이 있습니다.");
        string prefix="packages/"+package.Build+"/";
        var record=new Dictionary<string,object>{{"manifestSha256",Sha(package.Manifest)},{"files",package.Files}};
        if(marker==null) {
            string extensions=Path.Combine(parent,"extensions");Directory.CreateDirectory(extensions);NoLinks(extensions);
            string stage=Path.Combine(parent,".store-install-"+Guid.NewGuid().ToString("N"));NoLinks(stage);Directory.CreateDirectory(stage);
            var created=new List<string>();
            try {
                foreach(var item in package.Bytes){string path=Within(stage,item.Key);Directory.CreateDirectory(Path.GetDirectoryName(path));File.WriteAllBytes(path,item.Value);created.Add(item.Key);}
                marker=new Dictionary<string,object>{{"schemaVersion",1},{"product",Product},{"id",Id},{"packages",new Dictionary<string,object>{{package.Build,record}}}};
                File.WriteAllBytes(Path.Combine(stage,Owner),Encode(marker));created.Add(Owner);Owned(stage);
                NoLinks(extension);if(Directory.Exists(extension)||File.Exists(extension))throw new IOException("설치 경로가 변경되었습니다.");Directory.Move(stage,extension);
            } finally {if(Directory.Exists(stage)){RemoveFiles(stage,created);if(!Directory.EnumerateFileSystemEntries(stage).Any())Directory.Delete(stage,false);}}
        } else {
            var packages=Obj(marker["packages"]);
            if(packages.ContainsKey(package.Build)&&Text(Obj(packages[package.Build]),"manifestSha256")!=Sha(package.Manifest))throw new InvalidDataException("같은 빌드의 등록 정보가 달라 설치를 중단했습니다.");
            if(!packages.ContainsKey(package.Build)) {
                if(packages.Count>=64)throw new InvalidDataException("보관된 확장 버전이 많습니다. 스토어 확장을 제거한 뒤 다시 설치해 주세요. 다운로드와 설정은 유지됩니다.");
                string destination=Within(extension,"packages/"+package.Build), stage=Path.Combine(parent,".store-package-"+Guid.NewGuid().ToString("N"));
                NoLinks(stage);Directory.CreateDirectory(stage);var created=new List<string>();
                try {
                    foreach(var file in package.Files){string name=file.Key.Substring(prefix.Length),path=Within(stage,name);Directory.CreateDirectory(Path.GetDirectoryName(path));File.WriteAllBytes(path,package.Bytes[file.Key]);created.Add(name);}
                    NoLinks(destination);Directory.Move(stage,destination);
                    packages.Add(package.Build,record);WriteAtomic(Path.Combine(extension,Owner),Encode(marker));
                } catch {
                    if(Directory.Exists(destination)&&!Obj(Decode(Read(Path.Combine(extension,Owner),2*1024*1024))["packages"]).ContainsKey(package.Build)) {RemoveFiles(destination,created);if(!Directory.EnumerateFileSystemEntries(destination).Any())Directory.Delete(destination,false);}
                    throw;
                } finally {if(Directory.Exists(stage)){RemoveFiles(stage,created);if(!Directory.EnumerateFileSystemEntries(stage).Any())Directory.Delete(stage,false);}}
            }
            WriteAtomic(Path.Combine(extension,"extension.json"),package.Manifest);
        }
        if(preset!=null){
            NoLinks(presetTarget);Directory.CreateDirectory(Path.GetDirectoryName(presetTarget));NoLinks(presetTarget);
            WriteConnection(presetTarget,preset);
            Console.WriteLine("다운로드한 플랫폼 주소를 저장했습니다. 기존 KEY와 연결 설정은 유지됩니다.");
        }
        Console.WriteLine("설치 완료: AX Workspace를 완전히 종료한 뒤 다시 열면 P&T AI Square가 나타납니다.");
    }
    static void Uninstall(string parent) {
        parent=Full(parent);NoLinks(parent);string extension=Path.Combine(parent,"extensions",Id);NoLinks(extension);
        if(!Directory.Exists(extension)){Console.WriteLine("제거할 스토어 확장이 없습니다.");return;}
        string runtime=Path.Combine(parent,"local-ui","runtime.json");
        if(File.Exists(runtime)){
            var value=Decode(Read(runtime,65536));object pid;
            if(value.TryGetValue("pid",out pid)){
                try{var process=System.Diagnostics.Process.GetProcessById(Convert.ToInt32(pid));if(!process.HasExited)throw new InvalidDataException("AX Workspace를 완전히 종료한 뒤 스토어를 제거해 주세요.");}
                catch(ArgumentException){}
            }
        }
        var marker=Owned(extension);var files=new List<string>();
        foreach(var package in Obj(marker["packages"]))files.AddRange(Obj(Obj(package.Value)["files"]).Keys);
        // Verification above is all-or-nothing. Modified or extra files abort
        // before deleting anything; user data is outside this owned directory.
        File.Delete(Path.Combine(extension,"extension.json"));RemoveFiles(extension,files);
        File.Delete(Path.Combine(extension,Owner));if(!Directory.EnumerateFileSystemEntries(extension).Any())Directory.Delete(extension,false);
        Console.WriteLine("스토어 확장을 제거했습니다. 연결 설정, 다운로드와 설치한 기능은 유지했습니다.");
    }
    static void CheckControl(string directory) {
        directory=Full(directory);NoLinks(directory);
        if(!Directory.Exists(directory))return;
        if(Utf8.GetString(Read(Path.Combine(directory,"store.install-id"),128)).Trim()!=Product)throw new InvalidDataException("다른 프로그램의 설치 폴더입니다.");
        var required=new HashSet<string>(new[]{"StoreInstaller.exe","Uninstall.exe","store.install-id"},StringComparer.OrdinalIgnoreCase);
        var allowed=new HashSet<string>(required,StringComparer.OrdinalIgnoreCase);allowed.UnionWith(new[]{"NSIS-COPYING.txt","NSIS-Modern-UI-2.txt","THIRD_PARTY_NOTICES.md"});
        var found=FilesIn(directory);
        if(!required.IsSubsetOf(found)||!found.IsSubsetOf(allowed))throw new InvalidDataException("제거 도구 폴더에 다른 파일이 있습니다.");
    }
    static int Main(string[] args) {
        try {
            AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling",false);
            AppContext.SetSwitch("Switch.System.IO.BlockLongPaths",false);
            if(((args.Length==4||args.Length==5)&&args[0]=="install")||(args.Length==2&&args[0]=="uninstall")){
                string scope=Sha(Utf8.GetBytes(Full(args[1]).ToUpperInvariant()));
                using(var mutex=new Mutex(false,"Local\\AX.OrganizationStore.Installer."+scope)){
                    bool acquired;try{acquired=mutex.WaitOne(0);}catch(AbandonedMutexException){acquired=true;}
                    if(!acquired)throw new InvalidDataException("다른 스토어 설치 또는 제거가 진행 중입니다.");
                    try{if(args[0]=="install")Install(args[1],args[2],args[3],args.Length==5?args[4]:null);else Uninstall(args[1]);}finally{mutex.ReleaseMutex();}
                }
            }
            else if(args.Length==2&&args[0]=="check-host")Host(args[1]);
            else if(args.Length==2&&args[0]=="check-control")CheckControl(args[1]);
            else if(args.Length==2&&args[0]=="check-connection")Connection(args[1]);
            else throw new InvalidDataException("명령: install <CompanyAgent 폴더> <package.zip> <AX-Workspace.exe 또는 소스 폴더> [connection.json] / uninstall <CompanyAgent 폴더>");
            return 0;
        }catch(Exception error){Console.Error.WriteLine("P&T AI Square 설치/제거를 완료하지 못했습니다. "+error.Message);return 2;}
    }
}
