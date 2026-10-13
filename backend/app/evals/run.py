from app.config import get_settings
from app.repositories import Repository
from app.services import AssistantService
from app.schemas import AssistantRequest

def main() -> None:
    repo = Repository.seeded(); service = AssistantService(repo, get_settings())
    print('Evaluation cases:', len(repo.eval_cases))
    for case in repo.eval_cases:
        response = service.handle(AssistantRequest(message='please help'))
        print(case['id'], response.status)

if __name__ == '__main__': main()

