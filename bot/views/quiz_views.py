from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

import discord

AnswerSubmitHandler = Callable[[discord.Interaction, int, int], Awaitable[tuple[bool, str]]]
LobbyActionHandler = Callable[[discord.Interaction], Awaitable[tuple[bool, str]]]


@dataclass(slots=True)
class OptionDescriptor:
    index: int
    label: str
    text: str


class QuizAnswerView(discord.ui.View):
    def __init__(
        self,
        *,
        question_index: int,
        options: list[str],
        timeout: float,
        on_submit: AnswerSubmitHandler,
    ) -> None:
        super().__init__(timeout=timeout)
        self.question_index = question_index
        self._on_submit = on_submit
        self.message: discord.Message | None = None

        labels = ["A", "B", "C", "D"]
        styles = [
            discord.ButtonStyle.primary,
            discord.ButtonStyle.secondary,
            discord.ButtonStyle.secondary,
            discord.ButtonStyle.secondary,
        ]
        for idx, option in enumerate(options[:4]):
            descriptor = OptionDescriptor(idx, labels[idx], option)
            self.add_item(
                _AnswerButton(
                    descriptor=descriptor,
                    style=styles[idx],
                    submit_handler=self._on_submit,
                    question_index=question_index,
                )
            )

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                return


class _AnswerButton(discord.ui.Button["QuizAnswerView"]):
    def __init__(
        self,
        *,
        descriptor: OptionDescriptor,
        style: discord.ButtonStyle,
        submit_handler: AnswerSubmitHandler,
        question_index: int,
    ) -> None:
        super().__init__(
            label=f"{descriptor.label}. {descriptor.text}"[:80],
            style=style,
            custom_id=f"quiz_answer_{question_index}_{descriptor.index}",
        )
        self._descriptor = descriptor
        self._submit_handler = submit_handler
        self._question_index = question_index

    async def callback(self, interaction: discord.Interaction) -> None:
        accepted, message = await self._submit_handler(
            interaction, self._question_index, self._descriptor.index
        )
        if interaction.response.is_done():
            try:
                await interaction.followup.send(message, ephemeral=True)
            except discord.HTTPException:
                pass
            return
        try:
            await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            return


class LobbyView(discord.ui.View):
    def __init__(
        self,
        *,
        timeout: float,
        on_join: LobbyActionHandler,
        on_leave: LobbyActionHandler,
        on_start: LobbyActionHandler,
        on_cancel: LobbyActionHandler,
    ) -> None:
        super().__init__(timeout=timeout)
        self._on_join = on_join
        self._on_leave = on_leave
        self._on_start = on_start
        self._on_cancel = on_cancel

    @discord.ui.button(label="Join", style=discord.ButtonStyle.success)
    async def join_button(
        self, interaction: discord.Interaction, _: discord.ui.Button["LobbyView"]
    ) -> None:
        await self._handle_action(interaction, self._on_join)

    @discord.ui.button(label="Leave", style=discord.ButtonStyle.secondary)
    async def leave_button(
        self, interaction: discord.Interaction, _: discord.ui.Button["LobbyView"]
    ) -> None:
        await self._handle_action(interaction, self._on_leave)

    @discord.ui.button(label="Start Now", style=discord.ButtonStyle.primary)
    async def start_button(
        self, interaction: discord.Interaction, _: discord.ui.Button["LobbyView"]
    ) -> None:
        await self._handle_action(interaction, self._on_start)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel_button(
        self, interaction: discord.Interaction, _: discord.ui.Button["LobbyView"]
    ) -> None:
        await self._handle_action(interaction, self._on_cancel)

    async def _handle_action(
        self, interaction: discord.Interaction, handler: LobbyActionHandler
    ) -> None:
        _, message = await handler(interaction)
        if interaction.response.is_done():
            try:
                await interaction.followup.send(message, ephemeral=True)
            except discord.HTTPException:
                pass
            return
        try:
            await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            return
