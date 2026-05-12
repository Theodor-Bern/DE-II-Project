import requests
import json

GITHUB_TOKEN = ""  # Optional: paste your GitHub token here, or leave empty

url = "https://api.github.com/search/repositories"

params = {
    "q": "created:2025-01-01..2025-12-31 is:public archived:false",
    "sort": "stars",
    "order": "desc",
    "per_page": 100
}

headers = {
    "Accept": "application/vnd.github+json"
}

if GITHUB_TOKEN:
    headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

response = requests.get(url, params=params, headers=headers)
response.raise_for_status()

data = response.json()

print("Total count from GitHub search:", data["total_count"])
print("Number of repos fetched:", len(data["items"]))

print("\nExample repo data:\n")

for repo in data["items"][:5]:
    simple_repo = {
        "name": repo["name"],
        "full_name": repo["full_name"],
        "url": repo["html_url"],
        "description": repo["description"],
        "language": repo["language"],
        "stars": repo["stargazers_count"],
        "forks": repo["forks_count"],
        "watchers": repo["watchers_count"],
        "open_issues": repo["open_issues_count"],
        "created_at": repo["created_at"],
        "updated_at": repo["updated_at"],
        "pushed_at": repo["pushed_at"],
        "topics": repo["topics"]
    }

    print(json.dumps(simple_repo, indent=2, ensure_ascii=False))
    print("-" * 80)

with open("github_repos_raw.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print("\nSaved full raw response to github_repos_raw.json")